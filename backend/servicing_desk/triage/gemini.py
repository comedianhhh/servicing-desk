"""Gemini backend for triage: same contract as agent.py (proposal + model id), same system prompt.

Exists because the model is a replaceable part: the operator-approval, clock, and audit layers never see
which provider produced the proposal. AI Studio's free tier makes this the zero-cost way to run the desk.
"""

from __future__ import annotations

import logging
import time

from google import genai
from google.genai import errors, types

from ..config import settings
from .agent import SYSTEM
from .schema import TriageProposal

log = logging.getLogger("gemini")
RETRY_STATUS = {429, 503}


def propose(letter_text: str, *, client: genai.Client | None = None) -> tuple[TriageProposal, str]:
    client = client or genai.Client(api_key=settings.gemini_api_key)
    # The free tier answers 503 "high demand" in bursts; a short backoff keeps a busy minute from being
    # treated as a poisoned message by the worker. Anything else propagates.
    for attempt in range(6):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=f"<letter>\n{letter_text}\n</letter>",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    response_mime_type="application/json",
                    response_schema=TriageProposal,
                    temperature=0,
                ),
            )
            break
        except errors.APIError as e:
            if e.code not in RETRY_STATUS or attempt == 5:
                raise
            wait = 3 * (attempt + 1)
            log.warning("gemini %s; retrying in %ss", e.code, wait)
            time.sleep(wait)
    parsed = response.parsed
    if not isinstance(parsed, TriageProposal):
        parsed = TriageProposal.model_validate_json(response.text)
    return parsed, settings.gemini_model
