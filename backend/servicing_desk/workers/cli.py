"""`desk-worker <role>` — one process per consumer group in Kafka mode, or everything in one loop without it.

Roles: triage-worker | letter-worker | ledger-worker | credit-worker | saga-worker (consumer groups),
       relay (outbox → Kafka), clock (sweep due clocks), all (no Kafka: sweep + in-process relay).
`--once` runs a single pass and exits — what a Kubernetes CronJob wants for the clock sweep.
"""

from __future__ import annotations

import logging
import sys
import time

from ..config import settings
from ..db import session_scope
from ..handlers import REGISTRY
from ..outbox import relay_once as inprocess_relay
from ..telemetry import configure_logging, serve_metrics
from .clock_worker import sweep

log = logging.getLogger("desk-worker")


def _loop(step, label: str, once: bool = False) -> None:
    while True:
        try:
            with session_scope() as s:
                n = step(s)
            if n or once:
                log.info("%s: %d", label, n)
        except Exception:  # noqa: BLE001 — nothing was committed; next pass retries
            log.exception("%s failed", label)
            if once:
                raise SystemExit(1) from None
        if once:
            return
        time.sleep(settings.clock_poll_seconds)


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    serve_metrics(settings.metrics_port)
    args = argv if argv is not None else sys.argv[1:]
    once = "--once" in args
    args = [a for a in args if a != "--once"]
    role = (args or ["all"])[0]
    kafka = bool(settings.kafka_bootstrap)

    if role == "all":
        if kafka:
            raise SystemExit("KAFKA_BOOTSTRAP is set; run one role per process (relay, clock, <group>)")
        _loop(lambda s: sweep(s) + inprocess_relay(s), "sweep+relay", once)
    elif role == "clock":
        if kafka:
            from ..bus import relay_once as kafka_relay

            _loop(lambda s: sweep(s) + kafka_relay(s), "sweep+relay", once)
        else:
            _loop(sweep, "sweep", once)
    elif role == "relay":
        from ..bus import ensure_topic
        from ..bus import relay_once as kafka_relay

        ensure_topic()
        _loop(kafka_relay, "relay", once)
    elif role in REGISTRY:
        if not kafka:
            raise SystemExit(f"{role} as a separate process needs KAFKA_BOOTSTRAP; without Kafka run `desk-worker all`")
        from ..bus import ensure_topic, run_consumer

        ensure_topic()
        run_consumer(role, REGISTRY[role])
    else:
        raise SystemExit(f"unknown role {role!r}; one of all, clock, relay, {', '.join(REGISTRY)}")


if __name__ == "__main__":
    main()
