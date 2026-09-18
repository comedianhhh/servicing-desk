"""Outbox: idempotent consumption, plus the in-process relay used when there is no Kafka.

Delivery is tracked per consumer group, like a Kafka consumer group's offset: a group that registers late still
receives every event of its type it has not processed. `published_at` marks first delivery to the transport.

With KAFKA_BOOTSTRAP set, `bus.relay_once` publishes rows to the topic and `bus.run_consumer` drives the same
handlers as consumer groups. `consume()` is shared by both transports, so handler code never knows which one
it is running under.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .models import OutboxEvent, ProcessedEvent

Handler = Callable[[Session, OutboxEvent], None]


def consume(session: Session, consumer: str, event: OutboxEvent, fn: Handler) -> bool:
    """Run `fn` at most once per (consumer, event). Returns False if it was already processed."""
    seen = session.get(ProcessedEvent, {"consumer": consumer, "event_id": event.id})
    if seen is not None:
        return False
    fn(session, event)
    session.add(ProcessedEvent(consumer=consumer, event_id=event.id))
    return True


def unprocessed(session: Session, consumer: str, event_types: list[str], limit: int = 100) -> list[OutboxEvent]:
    done = exists().where(ProcessedEvent.consumer == consumer, ProcessedEvent.event_id == OutboxEvent.id)
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.event_type.in_(event_types), ~done)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def relay_once(session: Session, registry: dict[str, dict[str, Handler]] | None = None, limit: int = 100) -> int:
    """In-process transport: deliver each group the events it has not processed. A handler exception
    propagates, the caller rolls back, and the event is redelivered next pass — at-least-once, which is why
    consume() dedupes. Loops until quiet, so a handler that emits new events sees them delivered too."""
    if registry is None:
        from .handlers import REGISTRY

        registry = REGISTRY
    total = 0
    while True:
        n = 0
        for consumer, handlers in registry.items():
            for ev in unprocessed(session, consumer, list(handlers), limit):
                if consume(session, consumer, ev, handlers[ev.event_type]):
                    n += 1
                if ev.published_at is None:
                    ev.published_at = datetime.now(UTC)
            session.flush()
        total += n
        if n == 0:
            return total
