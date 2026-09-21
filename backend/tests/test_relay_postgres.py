"""Relay locking on real Postgres. The unit tests run on SQLite, which accepts `FOR UPDATE SKIP LOCKED` and
silently ignores it — so the one property that lets several relays run side by side was untested until here.
Skipped unless TEST_DATABASE_URL points at a Postgres database (CI provides one)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from servicing_desk import service
from servicing_desk.bus import claim_unpublished
from servicing_desk.models import Base, Clock, ClockKind, ClockStatus, OutboxEvent
from servicing_desk.workers.clock_worker import sweep

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL or not URL.startswith("postgresql"), reason="needs TEST_DATABASE_URL (postgres)")


@pytest.fixture
def pg():
    engine = create_engine(URL, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as s:
        s.add_all(OutboxEvent(aggregate_type="case", aggregate_id=f"c{i}", event_type="x", payload={"i": i}) for i in range(6))
        s.commit()
    yield Session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _fail_fast(session, ms: int = 2000):
    # A relay that *blocks* on another relay's rows is the bug. Make it a failure, not a hang.
    session.execute(text(f"SET LOCAL statement_timeout = {ms}"))


def test_two_relays_split_the_backlog_without_blocking(pg):
    a, b = pg(), pg()
    try:
        _fail_fast(a)
        mine = claim_unpublished(a, limit=3)  # transaction stays open: rows locked
        assert len(mine) == 3

        _fail_fast(b)
        theirs = claim_unpublished(b, limit=10)  # would block without SKIP LOCKED
        assert len(theirs) == 3
        assert {e.id for e in mine}.isdisjoint({e.id for e in theirs})

        a.commit()
        b.commit()
    finally:
        a.close()
        b.close()


def test_rows_return_to_the_pool_when_a_relay_dies_before_marking(pg):
    a = pg()
    _fail_fast(a)
    claimed = claim_unpublished(a, limit=6)
    assert len(claimed) == 6
    a.rollback()  # crash between produce and mark: nothing was marked published
    a.close()

    b = pg()
    try:
        _fail_fast(b)
        assert len(claim_unpublished(b, limit=10)) == 6  # at-least-once: every row is offered again
        b.rollback()
    finally:
        b.close()


def test_marked_rows_are_not_offered_again(pg):
    a = pg()
    try:
        _fail_fast(a)
        for e in claim_unpublished(a, limit=2):
            e.published_at = datetime.now(UTC)  # what relay_once does after the broker acks
        a.commit()
        assert len(claim_unpublished(a, limit=10)) == 4
        a.rollback()
    finally:
        a.close()


def test_two_sweepers_do_not_fire_the_same_clock_twice(pg):
    """The clock sweep uses the same SKIP LOCKED clause as the relay; a clock must fire once even if two
    CronJob pods overlap (concurrencyPolicy: Forbid makes that unlikely, not impossible)."""
    with pg() as s:
        case, _ = service.intake(s, body="Loan 1 -- dispute the fee.", channel="mail", received_on=date(2026, 9, 1))
        for _ in range(4):
            s.add(Clock(case_id=case.id, kind=ClockKind.ACK, calendar="reg_x_bd", citation="test", due_on=date(2026, 9, 8)))
        s.commit()

    a, b = pg(), pg()
    try:
        _fail_fast(a)
        assert sweep(a, today=date(2026, 9, 9)) == 4  # transaction open: rows locked, not yet committed
        _fail_fast(b)
        assert sweep(b, today=date(2026, 9, 9)) == 0  # skipped, not blocked, not double-fired
        a.commit()
        assert sweep(b, today=date(2026, 9, 9)) == 0  # now FIRED, so no longer PENDING
        b.rollback()
    finally:
        a.close()
        b.close()
    with pg() as s:
        assert s.query(Clock).filter(Clock.status == ClockStatus.FIRED).count() == 4
