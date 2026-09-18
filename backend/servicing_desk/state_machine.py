"""The only place case status changes.

A transition does four things in ONE transaction: bump the case (with an optimistic-lock check), append an
audit row, adjust clocks, and append outbox events. Nothing here talks to Kafka, the LLM, or a printer —
those consume the outbox. If the transaction fails, none of it happened, and the audit log says so.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import clocks as clk
from .models import AuditLog, Case, CaseStatus, CaseType, ClockKind, OutboxEvent

S = CaseStatus

# (from, to): who may drive it. "human" = operator approval required; "system" = worker may do it.
TRANSITIONS: dict[tuple[CaseStatus, CaseStatus], str] = {
    (S.RECEIVED, S.TRIAGE): "system",  # triage proposal recorded
    (S.TRIAGE, S.NOT_COVERED): "human",
    (S.TRIAGE, S.ROUTED_LOSS_MIT): "human",
    (S.TRIAGE, S.PAYOFF_REQUEST): "human",
    (S.TRIAGE, S.EXCEPTION_REVIEW): "human",
    (S.TRIAGE, S.ACK_PENDING): "human",
    (S.ACK_PENDING, S.EARLY_RESOLVED): "human",  # §1024.35(f)(1) / §1024.36(e)
    (S.ACK_PENDING, S.INVESTIGATING): "human",  # L1 sent
    (S.EXCEPTION_REVIEW, S.CLOSED): "human",  # L5 sent
    (S.EXCEPTION_REVIEW, S.ACK_PENDING): "human",  # exception did not hold
    (S.INVESTIGATING, S.EXTENDED): "human",  # L4 sent, before due date
    (S.INVESTIGATING, S.RESPONDED): "human",  # L2 / L3 / RFI response sent
    (S.EXTENDED, S.RESPONDED): "human",
    (S.RESPONDED, S.DOCS_REQUESTED): "human",  # borrower asked for relied-upon docs
    (S.RESPONDED, S.CLOSED): "human",
    (S.DOCS_REQUESTED, S.CLOSED): "human",  # L6 sent
    (S.PAYOFF_REQUEST, S.PAYOFF_REASONABLE_TIME): "human",  # bankruptcy / foreclosure / reverse / disaster
    (S.PAYOFF_REQUEST, S.CLOSED): "human",  # payoff statement sent
    (S.PAYOFF_REASONABLE_TIME, S.CLOSED): "human",
    (S.EARLY_RESOLVED, S.CLOSED): "system",
    (S.NOT_COVERED, S.CLOSED): "system",
}

# Transitions that are only legal once a specific letter exists on the case.
REQUIRED_LETTER: dict[tuple[CaseStatus, CaseStatus], set[str]] = {
    (S.ACK_PENDING, S.INVESTIGATING): {"L1"},
    (S.EXCEPTION_REVIEW, S.CLOSED): {"L5"},
    (S.INVESTIGATING, S.EXTENDED): {"L4"},
    (S.INVESTIGATING, S.RESPONDED): {"L2", "L3", "RFI_RESPONSE"},
    (S.EXTENDED, S.RESPONDED): {"L2", "L3", "RFI_RESPONSE"},
    (S.DOCS_REQUESTED, S.CLOSED): {"L6"},
    (S.PAYOFF_REQUEST, S.CLOSED): {"PAYOFF"},
    (S.PAYOFF_REASONABLE_TIME, S.CLOSED): {"PAYOFF"},
}


class TransitionError(Exception):
    pass


def audit(session: Session, case_id: str, actor: str, action: str, detail: dict | None = None) -> None:
    session.add(AuditLog(case_id=case_id, actor=actor, action=action, detail=detail or {}))


def emit(session: Session, case: Case, event_type: str, payload: dict | None = None) -> OutboxEvent:
    ev = OutboxEvent(
        aggregate_type="case", aggregate_id=case.id, event_type=event_type, payload={"case_id": case.id, **(payload or {})}
    )
    session.add(ev)
    return ev


def transition(
    session: Session,
    case: Case,
    to: CaseStatus,
    *,
    actor: str,
    expected_version: int | None = None,
    today: date | None = None,
    detail: dict | None = None,
) -> Case:
    frm = case.status
    key = (frm, to)
    if key not in TRANSITIONS:
        raise TransitionError(f"{frm.value} -> {to.value} is not a legal transition")
    if TRANSITIONS[key] == "human" and actor.startswith("system:"):
        raise TransitionError(f"{frm.value} -> {to.value} requires an operator")
    if expected_version is not None and case.version != expected_version:
        raise TransitionError(f"case changed underneath you (v{case.version} != v{expected_version})")
    if key in REQUIRED_LETTER:
        have = {letter.template for letter in case.letters if letter.sent_at is not None}
        if not have & REQUIRED_LETTER[key]:
            raise TransitionError(f"{to.value} requires one of {sorted(REQUIRED_LETTER[key])} to be sent first")

    today = today or date.today()
    try:
        _on_enter(session, case, to, today)
    except ValueError as e:
        raise TransitionError(str(e)) from e

    case.status = to
    case.version += 1
    audit(session, case.id, actor, "transition", {"from": frm.value, "to": to.value, **(detail or {})})
    emit(session, case, "case.transitioned", {"from": frm.value, "to": to.value, "version": case.version})
    return case


def _on_enter(session: Session, case: Case, to: CaseStatus, today: date) -> None:
    """Clock side effects. Every branch cites the rule that makes it exist."""
    if to == S.ACK_PENDING:
        if case.case_type not in (CaseType.NOE, CaseType.RFI):
            raise TransitionError("ACK_PENDING requires case_type NOE or RFI")
        if not any(c.kind == ClockKind.ACK for c in case.clocks):
            for c in clk.clocks_on_acknowledged(case):
                case.clocks.append(c)
                emit(session, case, "clock.scheduled", {"kind": c.kind.value, "due_on": c.due_on.isoformat(), "citation": c.citation})
            if case.case_type == CaseType.NOE:
                hold = next(c for c in case.clocks if c.kind == ClockKind.CREDIT_REPORTING_HOLD)
                emit(session, case, "credit-hold.requested", {"loan_id": case.loan_id, "until": hold.due_on.isoformat()})
    elif to == S.EXCEPTION_REVIEW:
        case.clocks.append(clk.make_clock(case, clk.EXCEPTION_NOTICE, base=today))
    elif to == S.INVESTIGATING:
        clk.satisfy(case, ClockKind.ACK)
    elif to == S.EXTENDED:
        case.clocks.append(clk.extend_response(case, today))
    elif to == S.RESPONDED:
        clk.satisfy(case, ClockKind.RESPONSE)
        clk.satisfy(case, ClockKind.EXTENSION)
    elif to == S.DOCS_REQUESTED:
        case.clocks.append(clk.make_clock(case, clk.DOCS, base=today))
    elif to == S.PAYOFF_REQUEST:
        case.clocks.append(clk.make_clock(case, clk.PAYOFF))
    elif to == S.PAYOFF_REASONABLE_TIME:
        clk.cancel_all(case)  # "within a reasonable time" — no fixed clock, §1026.36(c)(3)
    elif to in (S.CLOSED, S.NOT_COVERED, S.ROUTED_LOSS_MIT, S.EARLY_RESOLVED):
        if to == S.CLOSED:
            clk.satisfy(case, ClockKind.DOCS)
            clk.satisfy(case, ClockKind.PAYOFF)
            clk.satisfy(case, ClockKind.EXCEPTION_NOTICE)
        clk.cancel_all(case)
