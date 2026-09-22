"""Triage providers. `propose(letter_text, received_on=...)` returns (TriageProposal, model_id) whichever backend
is configured. Decision layers: `score`/`hybrid` decide locally (no key, no egress), `jev`/`jev-hybrid`
decide through TypeSafe's hosted API (key required, letter text leaves the machine). The receipt date goes to the model because timeliness (§1024.35(g)(1)(iii): more than a year
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
    elif settings.triage_provider in ("score", "hybrid"):
        from functools import partial

        from .score import propose as _s

        _p = partial(_s, base="gemini" if settings.triage_provider == "hybrid" else "stub")
    elif settings.triage_provider in ("jev", "jev-hybrid"):
        from functools import partial

        from .jev import propose as _j

        _p = partial(_j, base="gemini" if settings.triage_provider == "jev-hybrid" else "stub")
    else:
        from .agent import propose as _p
    return _p(letter_text, received_on=received_on or date.today())
