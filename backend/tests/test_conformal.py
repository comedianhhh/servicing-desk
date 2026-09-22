"""Conformal / calibration arithmetic without a model. The guarantee is the point: on exchangeable data the
prediction set must cover the true label at least 1-alpha of the time even when the scores are junk, so
the tests feed junk (and one well-behaved case) and check the bookkeeping that delivers it."""

from __future__ import annotations

import math
import random

from evals import conformal as C


def _rows(n: int, seed: int, sharp: bool) -> list[dict]:
    """Synthetic scored letters. `sharp`: the true label gets a large margin most of the time; otherwise the
    logits are noise, so any single label is a coin flip."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        y = rng.choice(C.OPTIONS)
        logp = [rng.gauss(0, 1) for _ in C.OPTIONS]
        if sharp and rng.random() < 0.9:
            logp[C.OPTIONS.index(y)] += 6.0
        probs = C._softmax(logp)
        rows.append({"id": f"s{i}", "y": y, "alt": None, "vote": probs, "logp": logp})
    return rows


def test_quantile_is_the_conformal_order_statistic():
    scores = [0.1, 0.5, 0.3, 0.9, 0.7]
    # n=5, alpha=0.2 -> ceil(6*0.8)=5th smallest = 0.9
    assert C._quantile(scores, 0.2) == 0.9
    # alpha small enough that k > n -> +inf (every label is in the set; the honest answer for tiny n)
    assert C._quantile(scores, 0.05) == math.inf


def test_softmax_temperature_flattens():
    logits = [4.0, 0.0, 0.0, 0.0, 0.0]
    assert max(C._softmax(logits, 1.0)) > max(C._softmax(logits, 5.0)) > 0.2
    assert abs(sum(C._softmax(logits, 3.0)) - 1) < 1e-9


def test_coverage_holds_on_noise_and_sets_are_wide():
    rows = _rows(400, seed=1, sharp=False)
    s = C.cross_conformal(rows, "logit", alpha=0.1, folds=10)
    assert s["coverage"] >= 0.85  # 1-alpha minus sampling slack
    assert s["mean_size"] > 3  # noise cannot be covered with small sets


def test_sharp_scores_give_singletons_that_are_right():
    rows = _rows(400, seed=2, sharp=True)
    s = C.cross_conformal(rows, "logit", alpha=0.1, folds=10)
    assert s["coverage"] >= 0.85
    assert s["singletons"] > 200
    assert s["singleton_wrong"] / s["singletons"] < 0.15


def test_metrics_on_perfect_and_useless_confidence():
    assert C.auroc([(0.9, True), (0.8, True), (0.2, False)]) == 1.0
    assert C.auroc([(0.5, True), (0.5, False)]) == 0.5
    assert C.auroc([(0.5, True)]) is None
    assert C.ece([(1.0, True)] * 10) == 0.0
    assert abs(C.ece([(1.0, False)] * 10) - 1.0) < 1e-9
