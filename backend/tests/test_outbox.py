from datetime import date

import pytest

from servicing_desk import outbox, service
from servicing_desk.models import ClockKind, ClockStatus, OutboxEvent, ProcessedEvent
from servicing_desk.triage.schema import TriageProposal
from servicing_desk.workers import triage_worker
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


def test_relay_delivers_once_per_consumer_even_if_registered_late(session, case, monkeypatch):
    # Stand in for the model: the worker's handler must still go through record_proposal.
    monkeypatch.setattr(triage_worker, "propose", lambda body: (TriageProposal.model_validate(proposal_dict()), "fake"))
    assert outbox.relay_once(session) >= 1
    assert len(case.proposals) == 1
    assert outbox.relay_once(session) == 0  # nothing new: offsets are per consumer
    assert len(case.proposals) == 1
    # a consumer that subscribes after the event was created still gets it — consumer-group semantics
    seen = []
    outbox.subscribe("correspondence.received", consumer="late-auditor")(lambda s, e: seen.append(e.id))
    try:
        assert outbox.relay_once(session) == 1
        assert seen and outbox.relay_once(session) == 0
    finally:
        outbox._HANDLERS["correspondence.received"] = [h for h in outbox._HANDLERS["correspondence.received"] if h[0] != "late-auditor"]


def test_handler_failure_leaves_event_unpublished_for_retry(session, case, monkeypatch):
    def boom(body):
        raise RuntimeError("model down")

    monkeypatch.setattr(triage_worker, "propose", boom)
    with pytest.raises(RuntimeError):
        outbox.relay_once(session)
    session.rollback()
    assert session.query(ProcessedEvent).count() == 0  # not marked processed → redelivered next pass


def test_clock_sweep_fires_once_and_emits_event(session, case):
    p = service.record_proposal(session, case, TriageProposal.model_validate(proposal_dict()), "fake")
    service.approve_triage(session, case, p, approved=p.proposed, operator="op-1", expected_version=case.version)
    session.flush()
    assert sweep(session, today=date(2026, 9, 9)) == 1  # ACK due 09-09
    assert sweep(session, today=date(2026, 9, 9)) == 0  # already FIRED
    ack = next(c for c in case.clocks if c.kind == ClockKind.ACK)
    assert ack.status == ClockStatus.FIRED
    due = session.query(OutboxEvent).filter_by(event_type="clock.due").one()
    assert due.payload["kind"] == "ACK" and due.aggregate_id == case.id
