"""Consumer groups → the events they handle. One registry, two transports: the in-process relay (tests,
single-process demo) and Kafka consumer groups (`desk-worker <group>`) both read from here."""

from __future__ import annotations

import logging
import time

import anthropic
from sqlalchemy.orm import Session

from .effects import CREDIT_HANDLERS, LEDGER_HANDLERS, LETTER_HANDLERS
from .models import Case, OutboxEvent
from .saga import ORCHESTRATOR_HANDLERS
from .service import record_proposal
from .triage import propose

log = logging.getLogger("triage-worker")


def on_correspondence_received(session: Session, event: OutboxEvent) -> None:
    """Ask the model for a proposal. Provider errors propagate: the event is not marked processed and is
    redelivered, which is the right behaviour for a 5xx or a network blip."""
    case = session.get(Case, event.payload["case_id"])
    if case is None or case.proposals:
        return
    try:
        proposal, model = propose(case.correspondence.body, received_on=case.correspondence.received_on)
    except anthropic.RateLimitError as e:
        retry_after = int(e.response.headers.get("retry-after", "30"))
        log.warning("rate limited; sleeping %ss before redelivery", retry_after)
        time.sleep(retry_after)
        raise
    except anthropic.APIStatusError as e:
        log.error("provider status %s on case %s: %s", e.status_code, case.id, e.message)
        raise
    except anthropic.APIConnectionError:
        log.warning("provider unreachable; will retry")
        raise
    record_proposal(session, case, proposal, model)


REGISTRY: dict[str, dict] = {
    "triage-worker": {"correspondence.received": on_correspondence_received},
    "letter-worker": LETTER_HANDLERS,
    "ledger-worker": LEDGER_HANDLERS,
    "credit-worker": CREDIT_HANDLERS,
    "saga-worker": ORCHESTRATOR_HANDLERS,
}
