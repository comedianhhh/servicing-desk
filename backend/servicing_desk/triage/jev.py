"""Decision by a hosted decision model: TypeSafe's Jev answers the enumerated fields as typed questions
returning probability distributions, in one request, instead of generating JSON.

The split is the same as `score.py`, and the option descriptions are imported from it, so switching between
the two changes the decision layer and nothing else:

    stub / gemini   extraction (three elements, quotes)
    jev             case_type, the (b)(n) or RFI category, each exception flag, and the confidence

`score.py` reads next-token logprobs off a local model and averages five option orders to cancel position
bias. Jev returns `probabilities` directly and answers every question in one round trip. What it costs is
the property the local scorer was chosen for: **letter text leaves the machine.** A desk running this
provider sends borrower correspondence to a third party, which is a data-residency decision for whoever
deploys it, not a default — hence `TRIAGE_PROVIDER` stays `stub`/`score` unless someone sets otherwise, and
the README says so next to the accuracy numbers.

TypeSafe's own documentation is explicit that `confidence` "summarizes distribution concentration, not
overall workflow correctness", so this provider's confidence is calibrated by `evals/conformal.py` exactly
as the local scorer's is. A distribution from a better model is still not a probability of being right.

API: POST {typesafe_base_url}/v1/systemone, `Authorization: Bearer`, model `jev-latest`. Choice answers
carry `choice`, `probabilities` (summing to 1) and `confidence`; Noul answers carry `noul`, the probability
the statement is true, and no separate confidence.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
import urllib.error
import urllib.request
from datetime import date

from ..config import settings
from .schema import TriageProposal
from .score import CASE_TYPES, ERROR_CATEGORIES, EXCEPTIONS, EXCEPTIONS_FOR, RFI_CATEGORIES

log = logging.getLogger("jev")
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 6
RETRY_CAP = 60.0


def _post(body: dict, timeout: float = 120) -> dict:
    """One request, with the backoff the Gemini provider had to learn: a busy minute upstream is not a
    poisoned message, and a worker that treats it as one loses the letter."""
    if not settings.typesafe_api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not set; the jev provider needs a key from console.typesafe.ai/keys")
    req = urllib.request.Request(
        settings.typesafe_base_url.rstrip("/") + "/v1/systemone",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.typesafe_api_key}"},
        method="POST",
    )
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == RETRY_ATTEMPTS - 1:
                raise RuntimeError(f"typesafe {e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from e
            wait = min(RETRY_CAP, 3 * 2**attempt) * (0.7 + 0.6 * random.random())
            log.warning("typesafe %s; retrying in %.0fs (attempt %d/%d)", e.code, wait, attempt + 1, RETRY_ATTEMPTS)
            time.sleep(wait)
    raise AssertionError("unreachable")


def questions() -> dict:
    """Every question at once — the documented shape, evaluated in parallel. Both category questions are
    asked unconditionally and the irrelevant one discarded; branching would cost a second round trip to
    learn something the case-type answer already tells us."""
    q = {
        "case_type": {"type": "choice", "instructions": "What is this letter?", "criteria": dict(CASE_TYPES)},
        "error_category": {
            "type": "choice",
            "instructions": "If the borrower asserts a servicing error, which kind does the letter assert?",
            "criteria": dict(ERROR_CATEGORIES),
        },
        "rfi_category": {
            "type": "choice",
            "instructions": "If the borrower requests information, what do they ask for?",
            "criteria": dict(RFI_CATEGORIES),
        },
    }
    for name, e in EXCEPTIONS.items():
        q[f"exc_{name}"] = {
            "type": "noul",
            "instructions": f"Is the following true of the letter? {e['statement']}",
            # A Noul without criteria leans yes; the documented shape describes both outcomes.
            "criteria": {"true": e["true"], "false": e["false"]},
        }
    return q


def _dist(a: dict) -> dict:
    """Shaped like score.py's diagnostics so evals/conformal.py reads either provider unchanged. `flips` is
    0 and `label_mass` 1.0 by construction: Jev returns a distribution, so there is no option order to
    average over and no probability mass leaking to tokens that are not answers."""
    return {
        "probs": {k: round(v, 4) for k, v in a["probabilities"].items()},
        "logp": {k: round(math.log(max(v, 1e-12)), 4) for k, v in a["probabilities"].items()},
        "flips": 0,
        "label_mass": 1.0,
    }


def propose(letter_text: str, received_on: date | None = None, *, base: str = "stub") -> tuple[TriageProposal, str]:
    """A proposal whose extraction fields come from `base` (stub or gemini) and whose enumerated fields and
    confidence come from Jev. Returns (proposal, "<base>+jev:<model>")."""
    received_on = received_on or date.today()
    if base == "gemini":
        from .gemini import propose as _base
    else:
        from .stub import propose as _base
    proposal, base_model = _base(letter_text, received_on=received_on)
    t0 = time.perf_counter()
    out = _post(
        {
            "state": f'<letter received="{received_on}">\n{letter_text}\n</letter>',
            "model": settings.typesafe_model,
            "questions": questions(),
        }
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    answers = out["answers"]
    case = answers["case_type"]
    key = "error_category" if case["choice"] == "NOE" else "rfi_category" if case["choice"] == "RFI" else None
    category = answers[key] if key else None
    # Only the exceptions the rule has for this case type, exactly as score.py gates them: §1024.35(g)(1)
    # for a notice of error, §1024.36(f)(1) for a request for information, none for anything else.
    flags = {n: answers[f"exc_{n}"]["noul"] for n in EXCEPTIONS_FOR.get(case["choice"], ())}
    proposal = proposal.model_copy(
        update={
            "case_type": case["choice"],
            "error_category": category["choice"] if key == "error_category" else None,
            "rfi_category": category["choice"] if key == "rfi_category" else None,
            "exception_candidates": [n for n, p in flags.items() if p >= settings.score_flag_threshold],
            "confidence": round(case["confidence"], 4),
            "rationale": _rationale(case, category) + (f" Extraction: {proposal.rationale}" if base == "gemini" else ""),
        }
    )
    proposal._scores = {
        "case_type": _dist(case),
        "category": _dist(category) if category else None,
        "exceptions": {
            n: {"probs": {"YES": round(p, 4), "NO": round(1 - p, 4)}, "logp": None, "flips": 0, "label_mass": 1.0}
            for n, p in flags.items()
        },
        "prefills": 1,  # one request whatever the question count; the honest unit for the cost column
        "latency_ms": round(latency_ms, 1),
        "usage": out.get("usage"),
    }
    return proposal, f"{base_model}+jev:{out.get('model') or settings.typesafe_model}"


def _rationale(case: dict, category: dict | None) -> str:
    ranked = sorted(case["probabilities"].items(), key=lambda kv: -kv[1])[:2]
    parts = [f"Jev chose {ranked[0][0]} p={ranked[0][1]:.2f} over {ranked[1][0]} p={ranked[1][1]:.2f} (confidence {case['confidence']:.2f})"]
    if category:
        parts.append(f"category {category['choice']} p={max(category['probabilities'].values()):.2f}")
    return "; ".join(parts) + "."
