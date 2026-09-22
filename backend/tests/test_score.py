"""The scoring provider without a model: a fake llama-server that answers with fixed next-token logprobs.
What is under test is the arithmetic and the bookkeeping — restricted softmax, rotation averaging, the
label→option mapping staying aligned under rotation, missing labels getting a floor not a zero — since
those are the parts that would silently produce a wrong-but-plausible distribution."""

from __future__ import annotations

import math
from datetime import date

import pytest

from servicing_desk.triage import score as S

RECEIVED = date(2026, 10, 15)


def _fake_server(monkeypatch, logprob_for_option):
    """logprob_for_option(option_name) -> logprob. The fake reads the option order out of the rendered prompt
    so the test controls the *option*, not the letter, exactly as a position-unbiased model would."""
    calls = {"tokenize": 0, "completion": 0, "orders": []}

    def post(path, body, timeout=120):
        if path == "/tokenize":
            calls["tokenize"] += 1
            return {"tokens": [ord(body["content"])]}  # one token per letter, ids distinct
        if path == "/apply-template":
            return {"prompt": body["messages"][1]["content"]}
        if path == "/completion":
            calls["completion"] += 1
            lines = [ln for ln in body["prompt"].splitlines() if len(ln) > 3 and ln[1:4] == " = "]
            order = [ln[4:] for ln in lines]  # option description in prompt order
            calls["orders"].append(order)
            top = [{"id": ord(S.LABELS[i]), "token": S.LABELS[i], "logprob": logprob_for_option(desc)} for i, desc in enumerate(order)]
            return {"completion_probabilities": [{"top_logprobs": top}]}
        raise AssertionError(path)

    monkeypatch.setattr(S, "_post", post)
    S._label_ids.clear()
    return calls


def test_restricted_softmax_normalises_over_labels_only_and_floors_missing():
    probs, mass = S._restricted_softmax({1: math.log(0.5), 2: math.log(0.25)}, [1, 2, 3])
    assert probs[0] > probs[1] > probs[2] > 0  # missing label 3 is below the lowest seen, not zero
    assert abs(sum(probs) - 1) < 1e-9
    assert abs(mass - 0.75) < 1e-9  # raw mass on the labels we asked about


def test_choose_averages_rotations_and_keeps_option_alignment(monkeypatch):
    options = {"NOE": "notice of error", "RFI": "request for info", "PAYOFF_REQUEST": "payoff"}
    calls = _fake_server(monkeypatch, lambda desc: {"request for info": 0.0, "notice of error": -2.0, "payoff": -4.0}[desc])
    c = S.choose("some letter", RECEIVED, "What is it?", options)
    assert c.top == "RFI" and c.flips == 0 and c.rotations == 3
    assert calls["completion"] == 3 and calls["orders"][1][0] == "request for info"  # rotated, and RFI still wins
    assert abs(sum(c.probs.values()) - 1) < 1e-9
    assert c.probs["RFI"] > c.probs["NOE"] > c.probs["PAYOFF_REQUEST"]
    assert calls["tokenize"] == 3  # label ids resolved once per label, then cached


def test_position_bias_shows_up_as_flips(monkeypatch):
    """A model that always prefers whatever sits at position A: the averaged answer is a tie broken by order,
    and every rotation but one disagrees with it — which is exactly what `flips` must report."""
    options = {"X": "x", "Y": "y", "Z": "z"}
    seen = []

    def post(path, body, timeout=120):
        if path == "/tokenize":
            return {"tokens": [ord(body["content"])]}
        if path == "/apply-template":
            return {"prompt": body["messages"][1]["content"]}
        seen.append(1)
        return {"completion_probabilities": [{"top_logprobs": [{"id": ord("A"), "token": "A", "logprob": 0.0}, {"id": ord("B"), "token": "B", "logprob": -5.0}, {"id": ord("C"), "token": "C", "logprob": -5.0}]}]}

    monkeypatch.setattr(S, "_post", post)
    S._label_ids.clear()
    c = S.choose("letter", RECEIVED, "q", options)
    assert c.flips == 2 and max(c.probs.values()) < 0.4  # no option can be confident under pure position bias


def test_decide_routes_category_and_flags(monkeypatch):
    def lp(desc):
        if desc.startswith("a written notice asserting"):
            return 0.0
        if desc.startswith("imposing a fee"):
            return 0.0
        # The yes/no options now carry each exception's own descriptions, so the fake matches on those.
        if desc == "yes":
            return 2.0 if S._CURRENT.get("q", "").startswith("Is the following true of the letter? the letter complains about the loan as a whole") else -6.0
        if desc == "no":
            return 0.0
        return -6.0

    calls = _fake_server(monkeypatch, lp)
    orig = S._question

    def q(question, options, order):  # remember which statement is being judged, for the fake
        S._CURRENT = {"q": question}
        return orig(question, options, order)

    monkeypatch.setattr(S, "_question", q)
    monkeypatch.setattr(S, "_CURRENT", {}, raising=False)
    d = S.decide("letter", RECEIVED)
    assert d.case_type.top == "NOE" and d.category and d.category.top == "b5"
    assert d.flags == ["OVERBROAD"]
    assert set(d.exceptions) == {"OVERBROAD", "DUPLICATIVE", "UNTIMELY"}  # §1024.35(g)(1): the NOE exceptions only
    assert d.diagnostics()["prefills"] == calls["completion"]


def test_exceptions_are_judged_only_where_the_rule_has_them(monkeypatch):
    _fake_server(monkeypatch, lambda desc: 0.0 if desc in (S.CASE_TYPES["LOSS_MIT"], "yes") else -6.0)
    d = S.decide("letter", RECEIVED)
    assert d.case_type.top == "LOSS_MIT" and d.exceptions == {} and d.flags == []  # a yes-happy model, nothing to say yes to


def test_propose_overrides_enumerated_fields_only(monkeypatch):
    # Match the option by identity, not by its opening words: the descriptions get rewritten between rounds.
    _fake_server(monkeypatch, lambda desc: 0.0 if desc in (S.CASE_TYPES["PAYOFF_REQUEST"], "no") else -6.0)
    proposal, model = S.propose("Please send me the payoff amount. Rebecca Lindqvist, loan 5510-220-9931", received_on=RECEIVED)
    assert proposal.case_type == "PAYOFF_REQUEST" and proposal.error_category is None and proposal.exception_candidates == []
    assert proposal.three_elements.loan_identifier.value == "5510-220-9931"  # extraction still from the base provider
    assert 0 < proposal.confidence <= 1
    # confidence is the calibrated (log-space, temperature-scaled) number; the vote share stays in diagnostics
    logp = proposal._scores["case_type"]["logp"]
    t = S.settings.score_temperature
    z = sum(math.exp((v - max(logp.values())) / t) for v in logp.values())
    assert abs(proposal.confidence - math.exp((logp["PAYOFF_REQUEST"] - max(logp.values())) / t) / z) < 1e-3
    assert proposal._scores["case_type"]["probs"]["PAYOFF_REQUEST"] > 0.9
    assert model.endswith("+score:" + S.settings.score_model)


def test_label_must_be_one_token(monkeypatch):
    monkeypatch.setattr(S, "_post", lambda path, body, timeout=120: {"tokens": [1, 2]})
    S._label_ids.clear()
    with pytest.raises(ValueError, match="not a single token"):
        S.label_token_id("A")


def test_judge_keeps_short_options_and_an_unclear_escape(monkeypatch):
    """Bare options here on purpose (see judge's docstring: the long descriptions help Jev and hurt a 4B),
    and doubt has somewhere to go instead of leaking into yes."""
    seen = {}

    def lp(desc):
        seen.setdefault("descs", set()).add(desc)
        return 0.0 if desc == S.UNCLEAR_OPTION else -3.0

    _fake_server(monkeypatch, lp)
    c = S.judge("letter", RECEIVED, S.EXCEPTIONS["CONFIDENTIAL"])
    assert c.top == "UNCLEAR"
    assert seen["descs"] == {"yes", "no", S.UNCLEAR_OPTION}
    assert c.rotations == 3


def test_confidence_averages_in_log_space_and_respects_temperature(monkeypatch):
    """Two rotations that disagree by a hair should not read as a 50/50 vote: the logit average keeps the
    margin, and a higher temperature only flattens it."""
    options = {"NOE": "notice of error", "RFI": "request for info"}
    calls = {"n": 0}

    def lp(desc):
        calls["n"] += 1
        # rotation 1: NOE ahead by 3 nats; rotation 2 (options reversed): NOE ahead by 0.1 nats
        return {"notice of error": 0.0, "request for info": -3.0 if calls["n"] <= 2 else -0.1}[desc]

    _fake_server(monkeypatch, lp)
    monkeypatch.setattr(S.settings, "score_temperature", 1.0)
    c = S.choose("letter", RECEIVED, "What is it?", options)
    assert c.top == "NOE" and c.flips == 0
    assert len(c.logprobs) == 2 and len(c.logprobs[0]) == 2
    assert c.confidence > c.probs["NOE"] - 0.05  # not degraded to a vote share
    monkeypatch.setattr(S.settings, "score_temperature", 10.0)
    assert 0.5 < c.confidence < 0.7  # flattened toward uniform, still ordered
