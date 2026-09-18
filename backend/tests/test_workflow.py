from datetime import date

import pytest

from servicing_desk import service
from servicing_desk.models import CaseStatus as S
from servicing_desk.models import ClockKind, ClockStatus, OutboxEvent, Proposal
from servicing_desk.state_machine import TransitionError, transition
from servicing_desk.triage.schema import TriageProposal
from tests.conftest import proposal_dict


def _propose(session, case, **overrides) -> Proposal:
    p = service.record_proposal(session, case, TriageProposal.model_validate(proposal_dict(**overrides)), "test-model")
    session.flush()
    assert case.status == S.TRIAGE
    return p


def _approve(session, case, p, **kw):
    service.approve_triage(session, case, p, approved=p.proposed, operator="op-1", expected_version=case.version, today=date(2026, 9, 2), **kw)
    session.flush()


def test_noe_gets_ack_response_and_credit_hold_clocks(session, case):
    p = _propose(session, case)
    _approve(session, case, p)
    assert case.status == S.ACK_PENDING
    by_kind = {c.kind: c for c in case.clocks}
    # received Tue 2026-09-01; Labor Day Mon 09-07 is skipped
    assert by_kind[ClockKind.ACK].due_on == date(2026, 9, 9)
    assert by_kind[ClockKind.RESPONSE].due_on == date(2026, 10, 15)  # 30 bd, (e)(3)(i)(C); Labor Day + Columbus Day skipped
    assert by_kind[ClockKind.RESPONSE].citation == "§1024.35(e)(3)(i)(C)"
    assert by_kind[ClockKind.CREDIT_REPORTING_HOLD].due_on == date(2026, 10, 31)  # 60 calendar days
    events = {e.event_type for e in session.query(OutboxEvent)}
    assert {"correspondence.received", "case.transitioned", "clock.scheduled", "credit-hold.requested"} <= events


def test_payoff_error_category_gets_7_day_clock(session, case):
    p = _propose(session, case, error_category="b6")
    _approve(session, case, p)
    resp = next(c for c in case.clocks if c.kind == ClockKind.RESPONSE)
    assert resp.due_on == date(2026, 9, 11)
    assert resp.citation == "§1024.35(e)(3)(i)(A)"


def test_foreclosure_category_is_capped_by_sale_date(session, case):
    p = _propose(session, case, error_category="b10")
    case.foreclosure_sale_date = date(2026, 9, 20)
    _approve(session, case, p)
    resp = next(c for c in case.clocks if c.kind == ClockKind.RESPONSE)
    assert resp.due_on == date(2026, 9, 20)


def test_rfi_gets_no_credit_hold(session, case):
    p = _propose(session, case, case_type="RFI", error_category=None, rfi_category="OWNER_IDENTITY")
    _approve(session, case, p)
    kinds = {c.kind for c in case.clocks}
    assert ClockKind.CREDIT_REPORTING_HOLD not in kinds
    assert next(c for c in case.clocks if c.kind == ClockKind.RESPONSE).due_on == date(2026, 9, 16)  # 10 bd


def test_operator_edit_is_what_gets_applied_and_is_audited(session, case):
    p = _propose(session, case, error_category="b11")
    edited = dict(p.proposed, error_category="b6")
    service.approve_triage(session, case, p, approved=edited, operator="op-1", expected_version=case.version)
    session.flush()
    assert case.error_category.value == "b6"
    assert p.approved["error_category"] == "b6" and p.proposed["error_category"] == "b11"
    from servicing_desk.models import AuditLog

    row = session.query(AuditLog).filter_by(action="triage.approved").one()
    assert row.detail["edited_fields"] == ["error_category"]


def test_transition_requires_letter(session, case):
    p = _propose(session, case)
    _approve(session, case, p)
    with pytest.raises(TransitionError, match="L1"):
        transition(session, case, S.INVESTIGATING, actor="op-1")
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": case.id}, operator="op-1")
    transition(session, case, S.INVESTIGATING, actor="op-1")
    ack = next(c for c in case.clocks if c.kind == ClockKind.ACK)
    assert ack.status == ClockStatus.SATISFIED


def test_extension_only_for_30_day_class_and_only_before_due(session, case):
    p = _propose(session, case, error_category="b6")  # 7-day class, not extendable
    _approve(session, case, p)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    transition(session, case, S.INVESTIGATING, actor="op-1")
    service.send_letter(session, case, "L4", {"original_due_on": "x", "new_due_on": "y", "reasons": "r"}, operator="op-1")
    with pytest.raises(TransitionError, match="not extendable"):
        transition(session, case, S.EXTENDED, actor="op-1", today=date(2026, 9, 3))


def test_extension_adds_15_bd_after_original_due(session, case):
    p = _propose(session, case, error_category="b11")
    _approve(session, case, p)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    transition(session, case, S.INVESTIGATING, actor="op-1")
    service.send_letter(session, case, "L4", {"original_due_on": "2026-10-15", "new_due_on": "2026-11-05", "reasons": "r"}, operator="op-1")
    transition(session, case, S.EXTENDED, actor="op-1", today=date(2026, 10, 1))
    ext = next(c for c in case.clocks if c.kind == ClockKind.EXTENSION)
    assert ext.due_on == date(2026, 11, 5)  # 15 bd after Thu 10-15 (no federal holiday in between)


def test_extension_notice_after_due_date_is_rejected(session, case):
    p = _propose(session, case, error_category="b11")
    _approve(session, case, p)
    service.send_letter(session, case, "L1", {"received_on": "2026-09-01", "reference": "x"}, operator="op-1")
    transition(session, case, S.INVESTIGATING, actor="op-1")
    service.send_letter(session, case, "L4", {"original_due_on": "2026-10-15", "new_due_on": "?", "reasons": "r"}, operator="op-1")
    with pytest.raises(TransitionError, match="before the original due date"):
        transition(session, case, S.EXTENDED, actor="op-1", today=date(2026, 10, 16))


def test_optimistic_lock_rejects_stale_operator(session, case):
    p = _propose(session, case)
    with pytest.raises(TransitionError, match="changed underneath"):
        service.approve_triage(session, case, p, approved=p.proposed, operator="op-2", expected_version=case.version - 1)


def test_system_actor_cannot_take_human_transition(session, case):
    p = _propose(session, case)
    _approve(session, case, p)
    with pytest.raises(TransitionError, match="requires an operator"):
        transition(session, case, S.EARLY_RESOLVED, actor="system:bot")


def test_duplicate_letter_does_not_open_second_case(session, case):
    from tests.conftest import NOE_LETTER

    again, created = service.intake(session, body="  " + NOE_LETTER.upper() + "\n", channel="email", received_on=date(2026, 9, 2))
    assert not created and again.id == case.id
