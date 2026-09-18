"""Gemini backend for triage — same contract as agent.py (proposal + model id), same system prompt.

Exists because the model is a replaceable part: the operator-approval, clock, and audit layers never see
which provider produced the proposal. AI Studio's free tier makes this the zero-cost way to run the desk.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from ..config import settings
from .agent import SYSTEM
from .schema import TriageProposal


def propose(letter_text: str, *, client: genai.Client | None = None) -> tuple[TriageProposal, str]:
    client = client or genai.Client(api_key=settings.gemini_api_key)
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
    parsed = response.parsed
    if not isinstance(parsed, TriageProposal):
        parsed = TriageProposal.model_validate_json(response.text)
    return parsed, settings.gemini_model
