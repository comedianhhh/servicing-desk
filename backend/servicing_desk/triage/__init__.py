"""Triage providers. `propose(letter_text, received_on=...)` returns (TriageProposal, model_id) whichever backend
is configured. The receipt date goes to the model because timeliness (§1024.35(g)(1)(iii): more than a year
after payoff or transfer) cannot be judged from the letter alone."""

from __future__ import annotations

from datetime import date

from ..config import settings
from .schema import TriageProposal


def propose(letter_text: str, received_on: date | None = None) -> tuple[TriageProposal, str]:
    if settings.triage_provider == "stub":
        from .stub import propose as _p
    elif settings.triage_provider == "gemini":
        from .gemini import propose as _p
    else:
        from .agent import propose as _p
    return _p(letter_text, received_on=received_on or date.today())
