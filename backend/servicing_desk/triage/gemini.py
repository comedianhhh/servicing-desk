"""Gemini backend for triage: same contract as agent.py (proposal + model id), same system prompt.

Exists because the model is a replaceable part: the operator-approval, clock, and audit layers never see
which provider produced the proposal. AI Studio's free tier makes this the zero-cost way to run the desk.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date

from google import genai
from google.genai import errors, types

from ..config import settings
from .agent import SYSTEM, wrap
from .schema import TriageProposal

log = logging.getLogger("gemini")
RETRY_STATUS = {429, 503}
RETRY_ATTEMPTS = 9
RETRY_CAP = 90.0  # seconds; 3, 6, 12, 24, 48, 90, 90, 90 with jitter ≈ 6 minutes of patience


def propose(
    letter_text: str, received_on: date | None = None, *, client: genai.Client | None = None, temperature: float = 0
) -> tuple[TriageProposal, str]:
    """`temperature` is 0 for the desk (one deterministic proposal) and >0 only for evals/votes.py, which samples."""
    client = client or genai.Client(api_key=settings.gemini_api_key)
    # The free tier answers 503 "high demand" in bursts and 429 when the per-minute rate is exceeded; backing
    # off keeps a busy minute from being treated as a poisoned message by the worker. Linear 3s steps over six
    # attempts (~1 minute) turned out to be too short: a 300-letter eval run died on a demand spike that lasted
    # longer than that. Exponential with jitter, capped, over ~8 minutes total. Anything else propagates.
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=wrap(letter_text, received_on),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    response_mime_type="application/json",
                    response_schema=TriageProposal,
                    temperature=temperature,
                ),
            )
            break
        except errors.APIError as e:
            if e.code not in RETRY_STATUS or attempt == RETRY_ATTEMPTS - 1:
                raise
            # Jitter so parallel workers that hit the same spike do not retry in lockstep.
            wait = min(RETRY_CAP, 3 * 2**attempt) * (0.7 + 0.6 * random.random())
            log.warning("gemini %s; retrying in %.0fs (attempt %d/%d)", e.code, wait, attempt + 1, RETRY_ATTEMPTS)
            time.sleep(wait)
    parsed = response.parsed
    if not isinstance(parsed, TriageProposal):
        parsed = TriageProposal.model_validate_json(response.text)
    return parsed, settings.gemini_model
