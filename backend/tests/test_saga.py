"""Respond saga through the in-process transport. The same handlers run as Kafka consumer groups."""

import pytest

from servicing_desk import effects, outbox, service
from servicing_desk.config import settings
from servicing_desk.models import AuditLog, CaseStatus, LedgerAdjustment, Saga, SagaState
from servicing_desk.state_machine import TransitionError, transition
from servicing_desk.triage.schema import TriageProposal
from tests.conftest import proposal_dict

L2 = {"correction_made": "reversed $75 late fee", "effective_date": "2026-09-20", "contact_phone": "800-555-0100", "adjustment_amount": "-75.00"}
L3 = {"reasons": "fee is contractual", "how_to_request_documents": "write to PO Box 1", "contact_phone": "800-555-0100"}


@pytest.fixture
def investigating(session, case):
    p = service.record_proposal(session, case, TriageProposal.model_validate(proposal_dict()), "fake")
    service.approve_triage(session, case, p, approved=p.proposed, operator="op-1", expected_version=case.version)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    outbox.relay_once(session)
    transition(session, case, CaseStatus.INVESTIGATING, actor="op-1")
    session.flush()
    return case


def _actions(session, case_id):
    return [a.action for a in session.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id)]


def test_happy_path_posts_ledger_then_delivers_then_responds(session, investigating):
    case = investigating
    saga = service.respond(session, case, "L2", L2, operator="op-1")
    assert saga.step == "apply_correction" and case.status == CaseStatus.INVESTIGATING
    outbox.relay_once(session)
    session.refresh(saga)
    assert saga.state == SagaState.DONE and saga.step == "finish"
    assert case.status == CaseStatus.RESPONDED
    adj = session.query(LedgerAdjustment).filter_by(saga_id=saga.id).one()
    assert adj.amount == "-75.00" and adj.reversed_at is None
    letter = next(lt for lt in case.letters if lt.template == "L2")
    assert letter.sent_at is not None and letter.voided_at is None
    acts = _actions(session, case.id)
    acts = acts[acts.index("saga.started") :]
    # order is the point: ledger first, then the letter, then the transition
    assert acts.index("ledger.adjusted") < acts.index("letter.delivered") < acts.index("saga.done")
    t = session.query(AuditLog).filter_by(case_id=case.id, action="transition").order_by(AuditLog.id.desc()).first()
    assert t.actor == "saga:op-1" and t.detail["to"] == "RESPONDED"


def test_no_error_letter_skips_the_ledger_step(session, investigating):
    case = investigating
    saga = service.respond(session, case, "L3", L3, operator="op-1")
    assert saga.step == "deliver_letter"
    outbox.relay_once(session)
    session.refresh(saga)
    assert saga.state == SagaState.DONE and case.status == CaseStatus.RESPONDED
    assert session.query(LedgerAdjustment).count() == 0


def test_retries_then_compensates_when_vendor_keeps_failing(session, investigating, monkeypatch):
    case = investigating
    calls = []

    def always_fail(letter):
        calls.append(letter.id)
        raise effects.DeliveryError("vendor returned 502")

    monkeypatch.setattr(effects, "deliver", always_fail)
    monkeypatch.setattr(settings, "saga_max_attempts", 3)
    saga = service.respond(session, case, "L2", L2, operator="op-1")
    outbox.relay_once(session)
    session.refresh(saga)
    assert len(calls) == 3
    assert saga.state == SagaState.COMPENSATED and saga.attempts == 3 and "502" in saga.last_error
    assert case.status == CaseStatus.INVESTIGATING  # never moved
    adj = session.query(LedgerAdjustment).filter_by(saga_id=saga.id).one()
    assert adj.reversed_at is not None  # compensation = forward reversing action, original posting kept
    letter = next(lt for lt in case.letters if lt.template == "L2")
    assert letter.sent_at is None and letter.voided_at is not None
    acts = _actions(session, case.id)
    assert acts.count("saga.retry") == 2 and "ledger.reversed" in acts and acts[-1] == "saga.compensated"


def test_transient_failure_then_success(session, investigating, monkeypatch):
    case = investigating
    outcomes = iter([effects.DeliveryError("502"), None])

    def flaky(letter):
        o = next(outcomes)
        if o:
            raise o

    monkeypatch.setattr(effects, "deliver", flaky)
    saga = service.respond(session, case, "L3", L3, operator="op-1")
    outbox.relay_once(session)
    session.refresh(saga)
    assert saga.state == SagaState.DONE and saga.attempts == 1
    assert case.status == CaseStatus.RESPONDED


def test_redelivery_does_not_double_post(session, investigating):
    case = investigating
    saga = service.respond(session, case, "L2", L2, operator="op-1")
    outbox.relay_once(session)
    # Simulate the transport redelivering the ledger command (at-least-once): handler is idempotent by saga_id.
    ev = session.query(outbox.OutboxEvent).filter_by(event_type="ledger.adjust.requested").one()
    effects.on_ledger_adjust_requested(session, ev)
    assert session.query(LedgerAdjustment).filter_by(saga_id=saga.id).count() == 1


def test_second_saga_on_same_case_is_refused(session, investigating):
    service.respond(session, investigating, "L3", L3, operator="op-1")
    with pytest.raises(ValueError, match="already running"):
        service.respond(session, investigating, "L3", L3, operator="op-1")


def test_saga_cannot_start_from_wrong_state(session, case):
    with pytest.raises(ValueError, match="cannot respond"):
        service.respond(session, case, "L3", L3, operator="op-1")


def test_system_actor_still_cannot_take_human_transitions(session, investigating):
    with pytest.raises(TransitionError, match="requires an operator"):
        transition(session, investigating, CaseStatus.RESPONDED, actor="system:anything")
    assert session.query(Saga).count() == 0


def test_standalone_letter_retries_itself(session, case, monkeypatch):
    outcomes = iter([effects.DeliveryError("502"), effects.DeliveryError("502"), None])

    def flaky(letter):
        o = next(outcomes)
        if o:
            raise o

    monkeypatch.setattr(effects, "deliver", flaky)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    outbox.relay_once(session)
    letter = case.letters[0]
    assert letter.sent_at is not None
    acts = _actions(session, case.id)
    assert acts.count("letter.delivery_failed") == 2 and acts[-1] == "letter.delivered"


def test_standalone_letter_gives_up_after_max_attempts(session, case, monkeypatch):
    monkeypatch.setattr(effects, "deliver", lambda letter: (_ for _ in ()).throw(effects.DeliveryError("502")))
    monkeypatch.setattr(settings, "saga_max_attempts", 3)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    outbox.relay_once(session)
    assert case.letters[0].sent_at is None
    acts = _actions(session, case.id)
    assert acts.count("letter.delivery_failed") == 3 and acts[-1] == "letter.delivery_abandoned"
