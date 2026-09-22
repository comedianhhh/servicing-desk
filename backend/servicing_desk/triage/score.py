"""Decision by next-token scoring: the enumerated fields of a proposal (type, category, exception flags) come
from one forward pass each, read as a probability distribution over the allowed answers, not from generated
text. The extraction fields (three elements, quotes) still come from a generating provider — scoring can only
choose among answers the desk already knows.

Backend: a local llama.cpp `llama-server` (any OpenAI-style server that exposes next-token logprobs would do).
For each decision the letter is rendered through the model's chat template with a question and lettered
options, the server returns the top next-token logprobs at the answer position, and the label tokens are
re-normalised among themselves (restricted softmax). Because small models prefer some letters over others,
every decision is scored under several rotations of the option order and the distributions are averaged; the
number of rotations whose top answer disagreed is kept as a diagnostic.

The `confidence` this produces is the top-1 probability of `case_type` after averaging the rotations in log
space and temperature scaling (`score_temperature`, fit by evals/conformal.py). Unlike the self-reported
number a generating model puts in a JSON field, it is a quantity the evals can calibrate — and did.
"""

from __future__ import annotations

import json
import logging
import math
import string
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from ..config import settings
from .schema import TriageProposal

log = logging.getLogger("score")

# Option descriptions are lifted from agent.SYSTEM so every provider decides against the same definitions.
CASE_TYPES: dict[str, str] = {
    "NOE": "a written notice asserting that the servicer made an error in servicing the loan (12 CFR 1024.35). "
    "Complaints about origination, underwriting, the interest rate, or other loan terms are NOT servicing errors "
    "even when the letter says 'error' or 'wrong'.",
    "RFI": "a written request for information about the loan (12 CFR 1024.36), including who owns or holds it.",
    "PAYOFF_REQUEST": "a request for the payoff amount or a payoff statement, and nothing else.",
    "LOSS_MIT": "a request for a modification, forbearance, or other loss mitigation option (12 CFR 1024.41).",
    "NOT_COVERED": "none of the above: a payment coupon, a general complaint with no asserted error and no "
    "request, marketing, a complaint about origination or loan terms.",
}
ERROR_CATEGORIES: dict[str, str] = {
    "b1": "failure to accept a conforming payment",
    "b2": "failure to apply an accepted payment to the loan",
    "b3": "failure to credit a payment as of the date it was received",
    "b4": "failure to pay taxes, insurance, or other escrow items on time",
    "b5": "imposing a fee the servicer lacks a reasonable basis to impose",
    "b6": "failure to provide an accurate payoff balance",
    "b7": "failure to provide accurate information about loss mitigation options or foreclosure",
    "b8": "failure to transfer information accurately to a transferee servicer",
    "b9": "making the first notice or filing for foreclosure too early (in violation of 1024.41(f) or (j))",
    "b10": "moving for judgment or order of sale, or conducting a sale, while loss mitigation rules forbid it",
    "b11": "any other error relating to the servicing of the loan",
}
RFI_CATEGORIES: dict[str, str] = {
    "OWNER_IDENTITY": "the letter asks who owns, holds, or is the assignee of the loan or note",
    "OTHER": "the letter asks for any other information about the loan",
}
# Each exception carries the statement being judged and a description of what a yes and a no look like.
# Spelling out the *no* is not decoration: a binary judgement with only the yes described leans yes, which is
# how round 4 produced OVERBROAD on 56 % of real complaints. TypeSafe's own Noul documentation and playground
# show the same shape (`criteria: {true, false}`), and both providers are given the same text so the evals
# compare decision layers rather than prompts.
EXCEPTIONS: dict[str, dict[str, str]] = {
    "OVERBROAD": {
        "statement": "the letter complains about the loan as a whole, or asks for all records about it, without "
        "naming any particular error or any particular document",
        "true": "The complaint or request covers the loan in general — everything that has gone wrong, the whole "
        "history, every record — and names no particular error and no particular document.",
        "false": "The letter names at least one concrete thing: a specific fee, payment, escrow item, statement, "
        "document, or event.",
    },
    "DUPLICATIVE": {
        "statement": "the letter itself says the borrower already sent this same notice or request before",
        "true": "The letter says the borrower sent this same notice or request before, or refers to an earlier "
        "letter of their own on the same subject.",
        "false": "The letter raises the matter for the first time, or its earlier contact was about something else.",
    },
    "UNTIMELY": {
        "statement": "the letter itself says the loan was paid off, discharged, or transferred to another servicer "
        "more than one year before the received date on the letter tag",
        "true": "The letter says the loan was paid off, discharged, or transferred away, and says it happened more "
        "than a year before the received date on the letter tag.",
        "false": "The loan is still open, or the payoff, discharge or transfer is recent, undated, or only implied.",
    },
    "CONFIDENTIAL": {
        "statement": "the letter asks for confidential, proprietary, or privileged information of the servicer",
        "true": "The letter asks for the servicer's own internal material: staff notes, legal advice, underwriting "
        "models, investor agreements, personnel records.",
        "false": "The letter asks about the borrower's own loan — including who owns it, how payments were applied, "
        "escrow analyses, and copies of the borrower's own documents.",
    },
    "IRRELEVANT": {
        "statement": "the letter asks for information that is not about this borrower's loan",
        "true": "The letter asks about a different loan, a different borrower, or a matter unconnected to this "
        "mortgage.",
        "false": "Everything the letter asks about concerns this borrower's own mortgage loan.",
    },
    "BURDENSOME": {
        "statement": "answering would be unduly burdensome: an unreasonable volume of documents or open-ended demand",
        "true": "Answering would mean producing an unreasonable volume of material — every document in the file, "
        "years of call recordings, an open-ended demand with no limit.",
        "false": "The request is for a defined set of documents or facts that a servicer keeps to hand.",
    },
}

EXCEPTIONS_FOR: dict[str, tuple[str, ...]] = {
    "NOE": ("OVERBROAD", "DUPLICATIVE", "UNTIMELY"),
    "RFI": tuple(EXCEPTIONS),
}

SYSTEM = (
    "You triage borrower correspondence for a mortgage servicer's Regulation X desk. You will be shown a letter "
    "and one multiple-choice question about it. Answer with the single letter of the best option and nothing else."
)
LABELS = string.ascii_uppercase


@dataclass
class Choice:
    """One scored decision: averaged distribution over the options, plus what the averaging hid."""

    probs: dict[str, float]  # option -> mean probability across rotations, sums to 1
    top: str
    flips: int  # rotations whose top option differed from the averaged top
    label_mass: float  # mean raw probability the model put on *any* label token — low means the prompt is off
    rotations: int
    latency_ms: float
    # Per rotation, the restricted log-probabilities in canonical option order. Averaging probabilities turns
    # five near-one-hot answers into a vote share; averaging *these* keeps the margins, which is what a
    # calibration step needs (evals/conformal.py). Kept out of `probs` so the provider's confidence stays
    # what the README documented.
    logprobs: list[list[float]] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """Top-1 probability after averaging the rotations in log space and dividing by
        `score_temperature`. Averaging the probabilities instead gives the share of option orders that
        agreed — a coarser number that reads as 1.0 whenever the orders happen to agree. The temperature
        is fit by the evals (evals/conformal.py); at 1.0 this is plain logit averaging."""
        if not self.logprobs:
            return self.probs[self.top]
        names = list(self.probs)
        mean = [sum(r[i] for r in self.logprobs) / len(self.logprobs) for i in range(len(names))]
        t = settings.score_temperature
        m = max(mean)
        ws = [math.exp((x - m) / t) for x in mean]
        return ws[names.index(self.top)] / sum(ws)


@dataclass
class Decision:
    case_type: Choice
    category: Choice | None
    exceptions: dict[str, Choice] = field(default_factory=dict)

    @property
    def flags(self) -> list[str]:
        return [name for name, c in self.exceptions.items() if c.probs["YES"] >= settings.score_flag_threshold]

    def diagnostics(self) -> dict:
        def one(c: Choice) -> dict:
            names = list(c.probs)
            logp = {n: round(sum(r[i] for r in c.logprobs) / len(c.logprobs), 4) for i, n in enumerate(names)} if c.logprobs else None
            return {"probs": {k: round(v, 4) for k, v in c.probs.items()}, "logp": logp, "flips": c.flips, "label_mass": round(c.label_mass, 3)}

        return {
            "case_type": one(self.case_type),
            "category": one(self.category) if self.category else None,
            "exceptions": {k: one(c) for k, c in self.exceptions.items()},
            "prefills": self.case_type.rotations
            + (self.category.rotations if self.category else 0)
            + sum(c.rotations for c in self.exceptions.values()),
            "latency_ms": round(
                self.case_type.latency_ms
                + (self.category.latency_ms if self.category else 0)
                + sum(c.latency_ms for c in self.exceptions.values()),
                1,
            ),
        }


# ---- llama-server transport -------------------------------------------------------------------------------


def _post(path: str, body: dict, timeout: float = 120) -> dict:
    req = urllib.request.Request(
        settings.score_base_url.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def render(system: str, user: str) -> str:
    """The prompt as the model was trained to see it, ending at the assistant's first token."""
    out = _post("/apply-template", {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return out["prompt"]


_label_ids: dict[str, int] = {}


def label_token_id(label: str) -> int:
    """Each label must be exactly one token at the answer position, or the logprob we read is not the answer."""
    if label not in _label_ids:
        ids = _post("/tokenize", {"content": label, "add_special": False})["tokens"]
        if len(ids) != 1:
            raise ValueError(f"label {label!r} is not a single token: {ids}")
        _label_ids[label] = ids[0]
    return _label_ids[label]


def next_token_logprobs(prompt: str, n_probs: int) -> dict[int, float]:
    """token id -> logprob for the top `n_probs` candidates at the position after `prompt`."""
    out = _post(
        "/completion",
        {
            "prompt": prompt,
            "n_predict": 1,
            "n_probs": n_probs,
            "temperature": 0,
            "top_k": 0,
            "top_p": 1.0,
            "min_p": 0.0,
            "samplers": [],
            "cache_prompt": True,
        },
    )
    first = out["completion_probabilities"][0]
    top = first.get("top_logprobs") or first.get("top_probs") or []
    result = {}
    for t in top:
        lp = t["logprob"] if "logprob" in t else math.log(max(t["prob"], 1e-12))
        result[t["id"]] = lp
    return result


# ---- decisions ---------------------------------------------------------------------------------------------


def _restricted_softmax(logprobs: dict[int, float], ids: list[int]) -> tuple[list[float], float]:
    """Softmax over the label tokens only. A label absent from the top-k gets a floor below the lowest seen
    entry rather than zero, so one missing letter cannot make the others certain. Returns (probs, raw mass)."""
    floor = min(logprobs.values()) - 2.0 if logprobs else -20.0
    lps = [logprobs.get(i, floor) for i in ids]
    m = max(lps)
    ws = [math.exp(lp - m) for lp in lps]
    z = sum(ws)
    mass = sum(math.exp(logprobs[i]) for i in ids if i in logprobs)
    return [w / z for w in ws], mass


def _question(question: str, options: dict[str, str], order: list[str]) -> str:
    lines = [f"{LABELS[i]} = {options[name]}" for i, name in enumerate(order)]
    return f"{question}\n\n" + "\n".join(lines) + "\n\nAnswer with the letter only."


def choose(letter_text: str, received_on: date, question: str, options: dict[str, str], rotations: int | None = None) -> Choice:
    names = list(options)
    n = len(names)
    rotations = min(rotations or settings.score_rotations, n) if n > 1 else 1
    ids = [label_token_id(LABELS[i]) for i in range(n)]
    sums = dict.fromkeys(names, 0.0)
    tops: list[str] = []
    logprobs: list[list[float]] = []
    mass_total = 0.0
    t0 = time.perf_counter()
    for r in range(rotations):
        order = names[r:] + names[:r]
        user = f'<letter received="{received_on}">\n{letter_text}\n</letter>\n\n' + _question(question, options, order)
        lps = next_token_logprobs(render(SYSTEM, user), n_probs=max(20, n + 5))
        probs, mass = _restricted_softmax(lps, ids)
        mass_total += mass
        by_name = dict(zip(order, probs, strict=True))
        for name, p in by_name.items():
            sums[name] += p
        logprobs.append([math.log(max(by_name[name], 1e-12)) for name in names])
        tops.append(order[max(range(n), key=probs.__getitem__)])
    avg = {k: v / rotations for k, v in sums.items()}
    top = max(avg, key=avg.__getitem__)
    return Choice(
        probs=avg,
        top=top,
        flips=sum(1 for t in tops if t != top),
        label_mass=mass_total / rotations,
        rotations=rotations,
        latency_ms=(time.perf_counter() - t0) * 1000,
        logprobs=logprobs,
    )


# Round 5: a third option. As a yes/no the small model said yes to OVERBROAD on 56 % of real complaints — a
# long letter with many grievances "does not identify a specific error" if you squint, and squinting is what a
# forced binary does. "Cannot tell" gives the doubt somewhere to go; only a clear yes becomes a candidate.
UNCLEAR_OPTION = "cannot tell from the letter"


def judge(letter_text: str, received_on: date, exception: dict[str, str]) -> Choice:
    """Three-way decision, scored under every option order so no letter carries the answer.

    The options stay bare words here. Putting each exception's `true` and `false` descriptions into the
    options — which is what TypeSafe's Noul format prescribes and what its model wants — was tried on both
    providers on the same 42 letters: spurious flags fell from 3 to 1 for Jev and rose from 3 to 7 for this
    4B model, whose OVERBROAD went from 2 letters to 9. A small model scoring a multiple-choice prompt
    degrades as the option text grows, whether the text is a negation (round 5's first attempt) or simply
    long. The flag questions are independent of the case-type question, so giving each provider the option
    text that works for it leaves the accuracy and calibration comparison untouched.
    """
    options = {"YES": "yes", "NO": "no", "UNCLEAR": UNCLEAR_OPTION}
    return choose(letter_text, received_on, f"Is the following true of the letter? {exception['statement']}", options)


def decide(letter_text: str, received_on: date) -> Decision:
    case = choose(letter_text, received_on, "What is this letter?", CASE_TYPES)
    category = None
    if case.top == "NOE":
        category = choose(letter_text, received_on, "Which kind of servicing error does the borrower assert?", ERROR_CATEGORIES)
    elif case.top == "RFI":
        category = choose(letter_text, received_on, "What does the borrower ask for?", RFI_CATEGORIES)
    # The exceptions exist only for notices of error (§1024.35(g)(1): duplicative, overbroad, untimely) and requests
    # for information (§1024.36(f)(1): all six). Judging them on a hardship letter or a payoff request produced the
    # round-4 noise — a loss-mit letter asking for "any assistance" is not an overbroad notice of anything.
    applicable = EXCEPTIONS_FOR.get(case.top, ())
    exceptions = {name: judge(letter_text, received_on, EXCEPTIONS[name]) for name in applicable}  # noqa: E501
    return Decision(case_type=case, category=category, exceptions=exceptions)


# ---- provider ----------------------------------------------------------------------------------------------


def propose(letter_text: str, received_on: date | None = None, *, base: str = "stub") -> tuple[TriageProposal, str]:
    """A proposal whose extraction fields come from `base` (stub or gemini) and whose enumerated fields and
    confidence come from scoring. Returns (proposal, "<base>+score:<model>")."""
    received_on = received_on or date.today()
    if base == "gemini":
        from .gemini import propose as _base
    else:
        from .stub import propose as _base
    proposal, base_model = _base(letter_text, received_on=received_on)
    d = decide(letter_text, received_on)
    proposal = proposal.model_copy(
        update={
            "case_type": d.case_type.top,
            "error_category": d.category.top if d.case_type.top == "NOE" and d.category else None,
            "rfi_category": d.category.top if d.case_type.top == "RFI" and d.category else None,
            "exception_candidates": d.flags,
            "confidence": round(d.case_type.confidence, 4),
            "rationale": _rationale(d) + (f" Extraction: {proposal.rationale}" if base == "gemini" else ""),
        }
    )
    proposal._scores = d.diagnostics()
    return proposal, f"{base_model}+score:{settings.score_model}"


def _rationale(d: Decision) -> str:
    ranked = sorted(d.case_type.probs.items(), key=lambda kv: -kv[1])[:2]
    parts = [f"Scored {ranked[0][0]} {d.case_type.confidence:.2f} (chosen by {ranked[0][1]:.0%} of option orders) vs {ranked[1][0]}"]
    if d.category:
        parts.append(f"category {d.category.top} {d.category.confidence:.2f}")
    if d.case_type.flips:
        parts.append(f"{d.case_type.flips}/{d.case_type.rotations} option orders disagreed")
    return "; ".join(parts) + "."
