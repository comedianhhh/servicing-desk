"""Logs and metrics. Two questions this must answer at 2 a.m.: *is the pipeline moving* (outbox backlog,
consumer lag by group, clocks past due that have not fired) and *what happened to case X* (every log line
carries the case id and event id it was working on).

Metrics are Prometheus counters/histograms/gauges, exposed on `/metrics` by the API and on METRICS_PORT by
each worker. Logs are one JSON object per line with whatever `bind()` context is active — Kafka group,
event id, case id — so `grep case_id=… ` across five workers reconstructs one case's story.

Deliberately not here: tracing. A single-topic outbox with dedupe has one story per case and the audit
table already tells it in order; a trace would repeat the audit log with worse retention.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# ---- log context ------------------------------------------------------------------------------------------

_ctx: ContextVar[dict | None] = ContextVar("log_ctx", default=None)


@contextmanager
def bind(**fields) -> Iterator[None]:
    """Attach fields to every log line emitted inside the block (nested binds merge)."""
    token = _ctx.set({**(_ctx.get() or {}), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **(_ctx.get() or {}),
        }
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


# ---- metrics ----------------------------------------------------------------------------------------------

EVENTS_CONSUMED = Counter(
    "desk_events_consumed_total",
    "Outbox events offered to a consumer group, by outcome (handled | deduped | failed)",
    ["group", "event_type", "outcome"],
)
HANDLER_SECONDS = Histogram(
    "desk_handler_seconds",
    "Time inside one handler, including its DB work",
    ["group", "event_type"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 30),
)
RELAY_PUBLISHED = Counter("desk_relay_published_total", "Outbox rows the relay marked published")
OUTBOX_BACKLOG = Gauge("desk_outbox_backlog", "Outbox rows not yet published (sampled by the relay)")
CLOCKS_FIRED = Counter("desk_clocks_fired_total", "Clocks the sweep fired", ["kind"])
CLOCKS_OVERDUE = Gauge("desk_clocks_overdue", "Pending clocks whose due date has passed and which have not fired (sampled by the sweep)")
TRIAGE_SECONDS = Histogram(
    "desk_triage_seconds",
    "Model call latency for one letter",
    ["provider"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)
TRIAGE_TOTAL = Counter("desk_triage_total", "Model triage calls by outcome (ok | error)", ["provider", "outcome"])
SAGA_TOTAL = Counter("desk_saga_total", "Respond sagas by final state (done | compensated)", ["outcome"])
HTTP_REQUESTS = Counter("desk_http_requests_total", "API requests", ["method", "route", "status"])
HTTP_SECONDS = Histogram("desk_http_request_seconds", "API request latency", ["method", "route"])


@contextmanager
def timed(histogram: Histogram, **labels) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        histogram.labels(**labels).observe(time.perf_counter() - start)


def serve_metrics(port: int | None) -> None:
    """Workers have no HTTP server of their own; this gives each one a /metrics on `port` (unset = off)."""
    if port:
        start_http_server(port)
        logging.getLogger("telemetry").info("metrics on :%d/metrics", port)
