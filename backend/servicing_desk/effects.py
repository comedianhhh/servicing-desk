"""Side-effect handlers: the things that talk to systems other than this database.

Each is a consumer-group handler: one DB transaction per event, idempotent via outbox.consume(). The external
systems are stubs (a letter vendor that can fail, a ledger table, a credit-hold table) — the shape of the
handler is what a real integration would keep.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Case, ClockKind, CreditHold, LedgerAdjustment, Letter, OutboxEvent
from .state_machine import audit, emit

log = logging.getLogger("effects")


# ---- letter vendor (consumer group: letter-worker) --------------------------------------------------------


class DeliveryError(Exception):
    pass


def deliver(letter: Letter) -> None:
    """Pretend mail vendor. LETTER_FAIL_RATE makes it flaky on purpose so the saga has something to survive."""
    if random.random() < settings.letter_fail_rate:  # noqa: S311 — demo, not crypto
        raise DeliveryError("vendor returned 502")


def on_letter_requested(session: Session, event: OutboxEvent) -> None:
    letter = session.get(Letter, event.payload["letter_id"])
    if letter is None or letter.sent_at is not None or letter.voided_at is not None:
        return
    case = session.get(Case, letter.case_id)
    passthrough = {k: v for k, v in event.payload.items() if k in ("saga_id", "letter_id")}
    attempt = int(event.payload.get("attempt", 1))
    try:
        deliver(letter)
    except DeliveryError as e:
        # A failed delivery is a business fact, not a transport error. Inside a saga the orchestrator decides
        # what happens next; a standalone letter retries itself, then gives up loudly.
        audit(session, case.id, "system:letter-worker", "letter.delivery_failed", {"letter_id": letter.id, "attempt": attempt, "error": str(e)})
        if passthrough.get("saga_id"):
            emit(session, case, "letter.delivery_failed", {**passthrough, "error": str(e)})
        elif attempt < settings.saga_max_attempts:
            emit(session, case, "letter.requested", {**passthrough, "template": letter.template, "attempt": attempt + 1})
        else:
            audit(session, case.id, "system:letter-worker", "letter.delivery_abandoned", {"letter_id": letter.id, "needs_attention": True})
        return
    letter.sent_at = datetime.now(UTC)
    audit(session, case.id, "system:letter-worker", "letter.delivered", {"letter_id": letter.id, "template": letter.template})
    emit(session, case, "letter.delivered", {**passthrough, "template": letter.template})


LETTER_HANDLERS = {"letter.requested": on_letter_requested}


# ---- servicing system of record (consumer group: ledger-worker) -------------------------------------------


def on_ledger_adjust_requested(session: Session, event: OutboxEvent) -> None:
    saga_id = event.payload["saga_id"]
    if session.scalar(select(LedgerAdjustment).where(LedgerAdjustment.saga_id == saga_id)):
        return  # already posted (redelivery)
    case = session.get(Case, event.payload["case_id"])
    adj = LedgerAdjustment(saga_id=saga_id, case_id=case.id, loan_id=case.loan_id, amount=event.payload["amount"], memo=event.payload["memo"])
    session.add(adj)
    session.flush()
    audit(session, case.id, "system:ledger-worker", "ledger.adjusted", {"adjustment_id": adj.id, "amount": adj.amount})
    emit(session, case, "ledger.adjusted", {"saga_id": saga_id, "adjustment_id": adj.id})


def on_ledger_reverse_requested(session: Session, event: OutboxEvent) -> None:
    adj = session.get(LedgerAdjustment, event.payload["adjustment_id"])
    if adj is None:
        return
    case = session.get(Case, adj.case_id)
    if adj.reversed_at is None:
        adj.reversed_at = datetime.now(UTC)
        audit(session, case.id, "system:ledger-worker", "ledger.reversed", {"adjustment_id": adj.id, "amount": adj.amount})
    emit(session, case, "ledger.reversed", {"saga_id": event.payload["saga_id"], "adjustment_id": adj.id})


LEDGER_HANDLERS = {
    "ledger.adjust.requested": on_ledger_adjust_requested,
    "ledger.reverse.requested": on_ledger_reverse_requested,
}


# ---- credit reporting (consumer group: credit-worker) -----------------------------------------------------


def on_credit_hold_requested(session: Session, event: OutboxEvent) -> None:
    case_id = event.payload["case_id"]
    if session.get(CreditHold, case_id) is not None:
        return
    hold = CreditHold(case_id=case_id, loan_id=event.payload.get("loan_id"), until=date.fromisoformat(event.payload["until"]))
    session.add(hold)
    audit(session, case_id, "system:credit-worker", "credit-hold.placed", {"until": event.payload["until"]})
    emit(session, session.get(Case, case_id), "credit-hold.placed", {"until": event.payload["until"]})


def on_clock_due(session: Session, event: OutboxEvent) -> None:
    """The 60-day hold ends when its clock fires — not when the case is answered. §1024.35(i)(1)."""
    if event.payload.get("kind") != ClockKind.CREDIT_REPORTING_HOLD.value:
        return
    hold = session.get(CreditHold, event.payload["case_id"])
    if hold is None or hold.released_at is not None:
        return
    hold.released_at = datetime.now(UTC)
    audit(session, hold.case_id, "system:credit-worker", "credit-hold.released", {"until": hold.until.isoformat()})
    emit(session, session.get(Case, hold.case_id), "credit-hold.released", {})


CREDIT_HANDLERS = {"credit-hold.requested": on_credit_hold_requested, "clock.due": on_clock_due}
