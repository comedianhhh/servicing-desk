"""Kafka transport for the outbox.

One topic, keyed by case id. A single topic (rather than one per event type) is deliberate: Kafka only orders
within a partition, and what must stay ordered here is "everything that happened to case X" — ack scheduled
before ack due, letter requested before letter delivered. Every consumer group sees every event and filters
by `event_type`; the per-group offset is what lets a group that starts late catch up.

Delivery is at-least-once at both ends:
- relay: produce → flush → mark published. A crash in between re-sends the event.
- consumer: handle in a DB transaction → commit DB → commit offset. A crash in between re-delivers it.
`outbox.consume()` dedupes on event id, which is what turns at-least-once into effectively-once.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import session_scope
from .models import OutboxEvent
from .outbox import consume
from .telemetry import OUTBOX_BACKLOG, RELAY_PUBLISHED

log = logging.getLogger("bus")


def encode(ev: OutboxEvent) -> bytes:
    return json.dumps(
        {
            "id": ev.id,
            "aggregate_type": ev.aggregate_type,
            "aggregate_id": ev.aggregate_id,
            "event_type": ev.event_type,
            "payload": ev.payload,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
    ).encode()


def decode(raw: bytes) -> OutboxEvent:
    d = json.loads(raw)
    ev = OutboxEvent(
        id=d["id"],
        aggregate_type=d["aggregate_type"],
        aggregate_id=d["aggregate_id"],
        event_type=d["event_type"],
        payload=d["payload"],
    )
    return ev  # transient: never added to a session; consumers only read it


def ensure_topic(partitions: int = 6, wait_seconds: int = 90) -> None:
    """Create the topic if missing. Waits for the broker rather than crashing: on a fresh cluster the
    workers usually start before Kafka is ready, and a crash-loop is noisier than a short wait."""
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            existing = admin.list_topics(timeout=5).topics
            break
        except KafkaException as e:
            if time.monotonic() > deadline:
                raise
            log.info("broker not ready (%s); retrying", e.args[0].str())
            time.sleep(3)
    if settings.kafka_topic in existing:
        return
    fut = admin.create_topics([NewTopic(settings.kafka_topic, num_partitions=partitions, replication_factor=1)])
    for topic, f in fut.items():
        try:
            f.result()
            log.info("created topic %s", topic)
        except KafkaException as e:  # several workers start at once; losing the race is fine
            if e.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise


_producer: Producer | None = None


def producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer(
            {
                "bootstrap.servers": settings.kafka_bootstrap,
                "acks": "all",
                "enable.idempotence": True,  # broker-side dedupe of producer retries
            }
        )
    return _producer


def claim_unpublished(session: Session, limit: int = 200) -> list[OutboxEvent]:
    """Lock a batch of unpublished rows for this transaction. `SKIP LOCKED` is what lets several relays run
    at once: a second relay does not block on the first one's rows, it takes the next ones. That is a
    Postgres guarantee — SQLite accepts the clause and ignores it, which is why `tests/test_relay_postgres.py`
    needs the real database."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(stmt))


def relay_once(session: Session, limit: int = 200) -> int:
    """Outbox → Kafka. Rows are locked so several relays can run; the row is marked only after the broker acks."""
    events = claim_unpublished(session, limit)
    if not events:
        return 0
    p = producer()
    delivered: dict[str, bool] = {}

    def _ack(err, msg, ev_id):
        delivered[ev_id] = err is None
        if err is not None:
            log.error("produce failed for %s: %s", ev_id, err)

    for ev in events:
        p.produce(
            settings.kafka_topic,
            key=ev.aggregate_id.encode(),
            value=encode(ev),
            headers=[("event_type", ev.event_type.encode())],
            on_delivery=lambda err, msg, ev_id=ev.id: _ack(err, msg, ev_id),
        )
    p.flush(30)
    now = datetime.now(UTC)
    n = 0
    for ev in events:
        if delivered.get(ev.id):
            ev.published_at = now
            n += 1
    RELAY_PUBLISHED.inc(n)
    session.flush()
    OUTBOX_BACKLOG.set(session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))) or 0)
    return n


Handler = Callable[[Session, OutboxEvent], None]


def run_consumer(group_id: str, handlers: dict[str, Handler], *, poll_timeout: float = 1.0, once: bool = False) -> None:
    """Generic consumer-group loop: one DB transaction per message, offsets committed after the DB commit."""
    c = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    c.subscribe([settings.kafka_topic])
    log.info("%s: subscribed to %s", group_id, settings.kafka_topic)
    try:
        while True:
            msg = c.poll(poll_timeout)
            if msg is None:
                if once:
                    return
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("%s: %s", group_id, msg.error())
                continue
            ev = decode(msg.value())
            fn = handlers.get(ev.event_type)
            if fn is not None:
                try:
                    with session_scope() as s:
                        if consume(s, group_id, ev, fn):
                            log.info("%s: %s %s", group_id, ev.event_type, ev.aggregate_id[:8])
                except Exception:  # noqa: BLE001 — offset not committed; message is redelivered after restart
                    log.exception("%s: handler failed on %s; not committing offset", group_id, ev.id)
                    raise
            c.commit(message=msg, asynchronous=False)
    finally:
        c.close()
