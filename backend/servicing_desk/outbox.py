"""Outbox relay and idempotent consumers.

Delivery is tracked per consumer, like a Kafka consumer group's offset: a consumer that registers late still
receives every event of its type it has not processed. `published_at` is informational (first delivery).

Step 1 (now): the relay calls registered handlers in-process, in creation order.
Step 2 (planned): the relay becomes a Kafka producer keyed by aggregate_id and the handlers run as consumer
groups. `consume()` already dedupes on event id, so handler code does not change.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .models import OutboxEvent, ProcessedEvent

Handler = Callable[[Session, OutboxEvent], None]
_HANDLERS: dict[str, list[tuple[str, Handler]]] = defaultdict(list)


def subscribe(event_type: str, consumer: str):
    def deco(fn: Handler) -> Handler:
        _HANDLERS[event_type].append((consumer, fn))
        return fn

    return deco


def consume(session: Session, consumer: str, event: OutboxEvent, fn: Handler) -> bool:
    """Run `fn` at most once per (consumer, event). Returns False if it was already processed."""
    seen = session.get(ProcessedEvent, {"consumer": consumer, "event_id": event.id})
    if seen is not None:
        return False
    fn(session, event)
    session.add(ProcessedEvent(consumer=consumer, event_id=event.id))
    return True


def unprocessed(session: Session, consumer: str, event_type: str, limit: int = 100) -> list[OutboxEvent]:
    done = exists().where(ProcessedEvent.consumer == consumer, ProcessedEvent.event_id == OutboxEvent.id)
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.event_type == event_type, ~done)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def relay_once(session: Session, limit: int = 100) -> int:
    """Deliver each consumer the events it has not processed. A handler exception propagates, the caller
    rolls back, and the event is redelivered next pass — at-least-once, which is why consume() dedupes."""
    n = 0
    for event_type, subs in _HANDLERS.items():
        for consumer, fn in subs:
            for ev in unprocessed(session, consumer, event_type, limit):
                if consume(session, consumer, ev, fn):
                    n += 1
                if ev.published_at is None:
                    ev.published_at = datetime.now(UTC)
    return n
