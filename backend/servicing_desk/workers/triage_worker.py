"""Consumes `correspondence.received`, asks the model for a proposal, records it. The model call is the
slow, fallible step, so it lives behind the outbox: an API error leaves the event unpublished and the
relay retries it; a duplicate delivery is dropped by the ProcessedEvent check in outbox.consume()."""

from __future__ import annotations

import logging
import time

import anthropic

from ..config import settings
from ..db import session_scope
from ..models import Case, OutboxEvent
from ..outbox import relay_once, subscribe
from ..service import record_proposal
from ..triage import propose

log = logging.getLogger("triage-worker")


@subscribe("correspondence.received", consumer="triage-worker")
def on_received(session, event: OutboxEvent) -> None:
    case = session.get(Case, event.payload["case_id"])
    if case is None or case.proposals:
        return
    try:
        proposal, model = propose(case.correspondence.body)
    except anthropic.RateLimitError as e:
        retry_after = int(e.response.headers.get("retry-after", "30"))
        log.warning("rate limited; retry in %ss", retry_after)
        time.sleep(retry_after)
        raise
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            log.warning("server error %s; will retry", e.status_code)
            raise
        log.error("bad request for case %s: %s", case.id, e.message)
        raise
    except anthropic.APIConnectionError:
        log.warning("network error; will retry")
        raise
    record_proposal(session, case, proposal, model)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with session_scope() as s:
                n = relay_once(s)
            if n:
                log.info("relayed=%d", n)
        except Exception:  # noqa: BLE001 — the event stays unpublished; next pass retries it
            log.exception("relay pass failed")
        time.sleep(settings.clock_poll_seconds)
