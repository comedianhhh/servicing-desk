from datetime import date

import pytest

from servicing_desk import handlers, outbox, service
from servicing_desk.models import ClockKind, ClockStatus, CreditHold, OutboxEvent, ProcessedEvent
from servicing_desk.triage.schema import TriageProposal
from servicing_desk.workers.clock_worker import sweep
from tests.conftest import proposal_dict


def test_consume_runs_handler_exactly_once_per_consumer(session, case):
    ev = session.query(OutboxEvent).filter_by(event_type="correspondence.received").one()
    calls = []
    assert outbox.consume(session, "c1", ev, lambda s, e: calls.append(e.id)) is True
    assert outbox.consume(session, "c1", ev, lambda s, e: calls.append(e.id)) is False
    assert outbox.consume(session, "c2", ev, lambda s, e: calls.append(e.id)) is True
    assert calls == [ev.id, ev.id]
    assert session.query(ProcessedEvent).count() == 2


def test_relay_delivers_once_per_group_even_if_registered_late(session, case):
    assert outbox.relay_once(session) >= 1
    assert len(case.proposals) == 1
    assert outbox.relay_once(session) == 0  # nothing new: offsets are per group
    # a group that registers after the event was created still gets it — consumer-group semantics
    seen = []
    registry = {**handlers.REGISTRY, "late-auditor": {"correspondence.received": lambda s, e: seen.append(e.id)}}
    assert outbox.relay_once(session, registry) == 1
    assert seen and outbox.relay_once(session, registry) == 0


def test_handler_failure_is_not_marked_processed(session, case, monkeypatch):
    def boom(body, **kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(handlers, "propose", boom)
    with pytest.raises(RuntimeError):
        outbox.relay_once(session)
    session.rollback()
    assert session.query(ProcessedEvent).count() == 0  # redelivered next pass


def test_clock_sweep_fires_once_and_releases_credit_hold(session, case):
    p = service.record_proposal(session, case, TriageProposal.model_validate(proposal_dict()), "fake")
    service.approve_triage(session, case, p, approved=p.proposed, operator="op-1", expected_version=case.version)
    outbox.relay_once(session)  # credit-worker places the hold
    hold = session.get(CreditHold, case.id)
    assert hold is not None and hold.until == date(2026, 10, 31) and hold.released_at is None

    assert sweep(session, today=date(2026, 9, 9)) == 1  # ACK due 09-09
    assert sweep(session, today=date(2026, 9, 9)) == 0  # already FIRED
    ack = next(c for c in case.clocks if c.kind == ClockKind.ACK)
    assert ack.status == ClockStatus.FIRED
    outbox.relay_once(session)
    assert hold.released_at is None  # ACK firing does not touch the hold

    assert sweep(session, today=date(2026, 10, 31)) == 2  # RESPONSE (10-15) and the 60-day hold
    outbox.relay_once(session)
    assert hold.released_at is not None  # §1024.35(i)(1): released by its own clock, not by the response
