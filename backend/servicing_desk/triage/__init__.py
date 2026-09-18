"""Triage providers. `propose(letter_text)` returns (TriageProposal, model_id) whichever backend is configured."""

from __future__ import annotations

from ..config import settings
from .schema import TriageProposal


def propose(letter_text: str) -> tuple[TriageProposal, str]:
    if settings.triage_provider == "stub":
        from .stub import propose as _p
    elif settings.triage_provider == "gemini":
        from .gemini import propose as _p
    else:
        from .agent import propose as _p
    return _p(letter_text)
