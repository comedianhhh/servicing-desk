"""Sweeps due clocks. A clock is a row, so a restart loses nothing; `FOR UPDATE SKIP LOCKED` lets several
sweepers run without double-firing (Postgres; no-op on SQLite in tests)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from ..models import Clock, ClockStatus
from ..state_machine import audit, emit


def sweep(session, today: date | None = None) -> int:
    today = today or date.today()
    stmt = (
        select(Clock)
        .where(Clock.status == ClockStatus.PENDING, Clock.due_on <= today)
        .with_for_update(skip_locked=True)
    )
    n = 0
    for clock in session.scalars(stmt):
        clock.status = ClockStatus.FIRED
        clock.fired_at = datetime.now(UTC)
        payload = {"clock_id": clock.id, "kind": clock.kind.value, "due_on": clock.due_on.isoformat(), "citation": clock.citation}
        emit(session, clock.case, "clock.due", payload)
        audit(session, clock.case_id, "system:clock-worker", "clock.due", payload)
        n += 1
    return n
