"""The Jev provider without the API: a fake transport returning the documented response shape. What is
under test is the wiring — that the request asks every question in one call, that the right category answer
is kept and the wrong one dropped, that exception flags are gated by case type, and that the extraction
fields still come from the base provider and are never overwritten by the decision layer."""

from __future__ import annotations

from datetime import date

import pytest

from servicing_desk.triage import jev as J

RECEIVED = date(2026, 10, 15)
LETTER = "Loan 5510-220-9931\nRebecca Lindqvist\n\nYou charged me a $95 property inspection fee. Please remove it."


def _fake(monkeypatch, case="NOE", case_probs=None, category="b5", nouls=None):
    """Answers every question the provider asked, in the documented shape. Records the request."""
    sent = {}

    def post(body, timeout=120):
        sent["body"] = body
        probs = case_probs or {"NOE": 0.9, "RFI": 0.05, "PAYOFF_REQUEST": 0.02, "LOSS_MIT": 0.02, "NOT_COVERED": 0.01}
        answers = {
            "case_type": {"type": "choice", "choice": case, "probabilities": probs, "confidence": max(probs.values())},
            "error_category": {"type": "choice", "choice": category, "probabilities": {"b5": 0.8, "b11": 0.2}, "confidence": 0.8},
            "rfi_category": {"type": "choice", "choice": "OTHER", "probabilities": {"OWNER_IDENTITY": 0.3, "OTHER": 0.7}, "confidence": 0.7},
        }
        for name in J.EXCEPTIONS:
            answers[f"exc_{name}"] = {"type": "noul", "noul": (nouls or {}).get(name, 0.02)}
        return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 300, "output_tokens": 30}}

    monkeypatch.setattr(J, "_post", post)
    return sent


def test_one_request_asks_every_question(monkeypatch):
    sent = _fake(monkeypatch)
    J.propose(LETTER, received_on=RECEIVED)
    q = sent["body"]["questions"]
    assert {"case_type", "error_category", "rfi_category"} <= set(q)
    assert all(f"exc_{n}" in q for n in J.EXCEPTIONS)  # all six asked; gating happens on the answers
    assert q["case_type"]["type"] == "choice" and q["exc_OVERBROAD"]["type"] == "noul"
    assert set(q["case_type"]["criteria"]) == set(J.CASE_TYPES)  # same definitions every provider decides against
    assert str(RECEIVED) in sent["body"]["state"] and "inspection fee" in sent["body"]["state"]


def test_noe_keeps_error_category_and_drops_rfi_category(monkeypatch):
    _fake(monkeypatch, case="NOE", category="b5")
    p, model = J.propose(LETTER, received_on=RECEIVED)
    assert p.case_type == "NOE" and p.error_category == "b5" and p.rfi_category is None
    assert model.endswith("+jev:jev-1.13.0")


def test_rfi_keeps_rfi_category_and_drops_error_category(monkeypatch):
    _fake(monkeypatch, case="RFI")
    p, _ = J.propose(LETTER, received_on=RECEIVED)
    assert p.case_type == "RFI" and p.rfi_category == "OTHER" and p.error_category is None


@pytest.mark.parametrize(
    ("case", "expected"),
    [("NOE", {"OVERBROAD", "DUPLICATIVE", "UNTIMELY"}), ("RFI", set(J.EXCEPTIONS)), ("LOSS_MIT", set()), ("PAYOFF_REQUEST", set())],
)
def test_exceptions_are_gated_by_case_type(monkeypatch, case, expected):
    """A model that says yes to everything must still produce no flags where the rule has no exceptions."""
    _fake(monkeypatch, case=case, nouls=dict.fromkeys(J.EXCEPTIONS, 0.99))
    p, _ = J.propose(LETTER, received_on=RECEIVED)
    assert set(p.exception_candidates) == expected
    assert set(p._scores["exceptions"]) == expected


def test_extraction_survives_the_decision_layer(monkeypatch):
    _fake(monkeypatch, case="NOE")
    p, _ = J.propose(LETTER, received_on=RECEIVED)
    assert p.three_elements.loan_identifier.value == "5510-220-9931"  # from the stub, not from Jev
    assert p.three_elements.loan_identifier.source_quote


def test_diagnostics_match_the_scoring_provider_shape(monkeypatch):
    _fake(monkeypatch, case="NOE")
    p, _ = J.propose(LETTER, received_on=RECEIVED)
    s = p._scores["case_type"]
    assert set(s) == {"probs", "logp", "flips", "label_mass"}  # evals/conformal.py reads this unchanged
    assert abs(sum(s["probs"].values()) - 1) < 1e-6
    assert s["logp"]["NOE"] > s["logp"]["NOT_COVERED"]
    assert p._scores["prefills"] == 1 and p._scores["usage"]["input_tokens"] == 300


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(J.settings, "typesafe_api_key", None)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        J._post({})
