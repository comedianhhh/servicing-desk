"""Metrics move at the seams and log lines carry the case they were about."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from servicing_desk import outbox, telemetry
from servicing_desk.api import main
from servicing_desk.models import OutboxEvent


def _value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_consume_counts_handled_deduped_and_failed(session):
    ev = OutboxEvent(aggregate_type="case", aggregate_id="c1", event_type="t.x", payload={})
    session.add(ev)
    session.flush()
    before = {k: _value(telemetry.EVENTS_CONSUMED, group="g", event_type="t.x", outcome=k) for k in ("handled", "deduped", "failed")}

    assert outbox.consume(session, "g", ev, lambda s, e: None) is True
    assert outbox.consume(session, "g", ev, lambda s, e: None) is False  # second delivery: deduped

    def boom(s, e):
        raise RuntimeError("x")

    ev2 = OutboxEvent(aggregate_type="case", aggregate_id="c1", event_type="t.x", payload={})
    session.add(ev2)
    session.flush()
    with pytest.raises(RuntimeError):
        outbox.consume(session, "g", ev2, boom)

    after = {k: _value(telemetry.EVENTS_CONSUMED, group="g", event_type="t.x", outcome=k) for k in before}
    assert {k: after[k] - before[k] for k in before} == {"handled": 1, "deduped": 1, "failed": 1}


def test_log_lines_inside_a_handler_carry_the_case_id(session, capsys):
    ev = OutboxEvent(aggregate_type="case", aggregate_id="case-42", event_type="t.y", payload={})
    session.add(ev)
    session.flush()
    handler = logging.StreamHandler()
    handler.setFormatter(telemetry.JsonFormatter())
    log = logging.getLogger("test-handler")
    log.addHandler(handler)
    log.propagate = False
    try:
        outbox.consume(session, "g2", ev, lambda s, e: log.warning("looking at it"))
        log.warning("outside")
    finally:
        log.removeHandler(handler)
    inside, outside = (json.loads(line) for line in capsys.readouterr().err.strip().splitlines())
    assert inside["msg"] == "looking at it" and inside["case_id"] == "case-42" and inside["group"] == "g2" and inside["event_id"] == ev.id
    assert "case_id" not in outside  # context does not leak past the handler


def test_metrics_endpoint_serves_prometheus_text(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    monkeypatch.setattr(main, "engine", engine)  # lifespan runs create_all against this, not the dev Postgres
    with TestClient(main.app) as c:
        c.get("/healthz")
        r = c.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert 'desk_http_requests_total{method="GET",route="/healthz",status="200"}' in r.text
    assert "desk_outbox_backlog" in r.text and "desk_clocks_overdue" in r.text
