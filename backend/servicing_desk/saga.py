"""The Respond saga — orchestration, not choreography, because this industry wants one row that says where
a multi-system action is and who started it (§1024.38(c)).

    start ─► [apply_correction] ─► deliver_letter ─► finish (case → RESPONDED)
                  │                     │
                  │                     └─ fails N times ─► COMPENSATING: void letter, reverse ledger ─► COMPENSATED
                  └─ (skipped when the letter carries no adjustment)

Order matters: the correction is posted to the ledger *before* the borrower is told it is effective. If the
letter then cannot be delivered, the compensation is a new forward action (a reversing adjustment), not a
rollback — the original posting stays in the ledger's history. There is no distributed transaction anywhere;
each step is one local transaction plus an outbox event.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import letters as letters_mod
from .config import settings
from .models import Case, CaseStatus, LedgerAdjustment, Letter, OutboxEvent, Saga, SagaState
from .state_machine import audit, emit, transition
from .telemetry import SAGA_TOTAL

log = logging.getLogger("saga")

RESPOND = "respond"


# ---- start -----------------------------------------------------------------------------------------------


def start_respond(session: Session, case: Case, template: str, fields: dict, *, operator: str) -> Saga:
    """Operator action. Creates the (undelivered) letter and the saga row, and emits the first command."""
    if template not in {"L2", "L3", "RFI_RESPONSE"}:
        raise ValueError("respond saga takes L2, L3 or RFI_RESPONSE")
    if case.status not in (CaseStatus.INVESTIGATING, CaseStatus.EXTENDED):
        raise ValueError(f"cannot respond from {case.status.value}")
    if session.scalar(select(Saga).where(Saga.case_id == case.id, Saga.state == SagaState.RUNNING)):
        raise ValueError("a respond saga is already running for this case")

    letter = letters_mod.render(case, template, fields)
    case.letters.append(letter)
    session.flush()
    amount = letter.fields.get("adjustment_amount")
    saga = Saga(
        kind=RESPOND,
        case_id=case.id,
        step="apply_correction" if amount else "deliver_letter",
        started_by=operator,
        data={"letter_id": letter.id, "template": template, "amount": amount},
    )
    session.add(saga)
    session.flush()
    audit(session, case.id, operator, "saga.started", {"saga_id": saga.id, "step": saga.step})
    _emit_step(session, case, saga)
    return saga


def _emit_step(session: Session, case: Case, saga: Saga) -> None:
    if saga.step == "apply_correction":
        emit(session, case, "ledger.adjust.requested", {"saga_id": saga.id, "amount": saga.data["amount"], "memo": saga.data["template"]})
    elif saga.step == "deliver_letter":
        emit(session, case, "letter.requested", {"saga_id": saga.id, "letter_id": saga.data["letter_id"]})
    else:
        raise ValueError(saga.step)


# ---- orchestrator handlers (consumer group: saga-worker) --------------------------------------------------


def _saga_for(session: Session, event: OutboxEvent) -> Saga | None:
    sid = event.payload.get("saga_id")
    if not sid:
        return None  # not a saga-driven event (e.g. a manually sent L1)
    saga = session.get(Saga, sid)
    if saga is None or saga.state not in (SagaState.RUNNING, SagaState.COMPENSATING):
        return None
    return saga


def on_ledger_adjusted(session: Session, event: OutboxEvent) -> None:
    saga = _saga_for(session, event)
    if saga is None or saga.step != "apply_correction":
        return
    case = session.get(Case, saga.case_id)
    saga.step = "deliver_letter"
    saga.attempts = 0
    audit(session, case.id, "system:saga", "saga.step", {"saga_id": saga.id, "step": saga.step})
    _emit_step(session, case, saga)


def on_letter_delivered(session: Session, event: OutboxEvent) -> None:
    saga = _saga_for(session, event)
    if saga is None or saga.step != "deliver_letter":
        return
    case = session.get(Case, saga.case_id)
    saga.step = "finish"
    # The saga acts for the operator who started it; the actor string keeps both facts.
    transition(session, case, CaseStatus.RESPONDED, actor=f"saga:{saga.started_by}", detail={"saga_id": saga.id})
    saga.state = SagaState.DONE
    SAGA_TOTAL.labels("done").inc()
    audit(session, case.id, "system:saga", "saga.done", {"saga_id": saga.id})


def on_letter_delivery_failed(session: Session, event: OutboxEvent) -> None:
    saga = _saga_for(session, event)
    if saga is None or saga.step != "deliver_letter":
        return
    case = session.get(Case, saga.case_id)
    saga.attempts += 1
    saga.last_error = event.payload.get("error")
    if saga.attempts < settings.saga_max_attempts:
        audit(session, case.id, "system:saga", "saga.retry", {"saga_id": saga.id, "attempt": saga.attempts, "error": saga.last_error})
        _emit_step(session, case, saga)
        return
    # give up: compensate
    saga.state = SagaState.COMPENSATING
    letter = session.get(Letter, saga.data["letter_id"])
    letter.voided_at = datetime.now(UTC)
    audit(session, case.id, "system:saga", "saga.compensating", {"saga_id": saga.id, "voided_letter": letter.id, "error": saga.last_error})
    adj = session.scalar(select(LedgerAdjustment).where(LedgerAdjustment.saga_id == saga.id, LedgerAdjustment.reversed_at.is_(None)))
    if adj is not None:
        emit(session, case, "ledger.reverse.requested", {"saga_id": saga.id, "adjustment_id": adj.id})
    else:
        _compensated(session, case, saga)


def on_ledger_reversed(session: Session, event: OutboxEvent) -> None:
    saga = _saga_for(session, event)
    if saga is None or saga.state != SagaState.COMPENSATING:
        return
    _compensated(session, session.get(Case, saga.case_id), saga)


def _compensated(session: Session, case: Case, saga: Saga) -> None:
    saga.state = SagaState.COMPENSATED
    SAGA_TOTAL.labels("compensated").inc()
    audit(session, case.id, "system:saga", "saga.compensated", {"saga_id": saga.id, "needs_attention": True})
    emit(session, case, "saga.compensated", {"saga_id": saga.id, "kind": saga.kind})


ORCHESTRATOR_HANDLERS = {
    "ledger.adjusted": on_ledger_adjusted,
    "letter.delivered": on_letter_delivered,
    "letter.delivery_failed": on_letter_delivery_failed,
    "ledger.reversed": on_ledger_reversed,
}
