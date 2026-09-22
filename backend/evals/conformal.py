"""Is the scoring provider's distribution usable as a probability? Three answers on one results file.

Usage: python -m evals.conformal [--set cfpb] [--alpha 0.1] [--folds 10] [score hybrid]

Reads results-<provider>.jsonl (or results-<set>-<provider>.jsonl), takes the per-option `case_type`
distribution the scoring provider recorded, and evaluates three ways of turning it into a number:

  vote    the averaged probabilities — what `confidence` is today. Each rotation is near one-hot, so this
          is really the share of option orders that agreed.
  logit   softmax of the per-rotation log-probabilities averaged in log space. Keeps the margins the
          probability average throws away.
  logit/T the same after temperature scaling; T is fit by minimum NLL on held-out letters.

For each: AUROC (does the number separate right from wrong), ECE (does 0.9 mean 90%), and a
cross-conformal prediction set at the requested coverage 1-alpha. Conformal is the one that comes with a
guarantee that does not depend on the model being calibrated: with exchangeable letters the set contains
the true label at least 1-alpha of the time, whatever the scores look like. The desk-relevant readouts are
how often the set is a single label (auto-routable) and how often that single label is wrong.

Split conformal with k folds: for each fold, the other folds are the calibration set (split in two when
temperature is fit, so the quantile is never taken on the letters that chose T); the fold is scored.
Unlabeled rows (cfpb `source=open`) are skipped.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter

from . import run

OPTIONS = ["NOE", "RFI", "PAYOFF_REQUEST", "LOSS_MIT", "NOT_COVERED"]


# ---- scores ------------------------------------------------------------------------------------------------


def _softmax(logits: list[float], t: float = 1.0) -> list[float]:
    m = max(logits)
    ws = [math.exp((x - m) / t) for x in logits]
    z = sum(ws)
    return [w / z for w in ws]


def _load(provider: str) -> list[dict]:
    path = run.results_path(provider)
    labels = {L["id"]: L for L in run.LETTERS}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        r = json.loads(line)
        L = labels.get(r["id"])
        s = (r["got"].get("scores") or {}).get("case_type")
        if not L or not L.get("case_type") or not s or not s.get("logp"):
            continue  # unlabeled, or a results file written before logp was recorded
        rows.append(
            {
                "id": r["id"],
                "y": L["case_type"],
                "alt": L.get("alt_case_type"),
                "vote": [s["probs"][o] for o in OPTIONS],
                "logp": [s["logp"][o] for o in OPTIONS],
            }
        )
    return rows


def _fit_temperature(rows: list[dict]) -> float:
    """Grid search T minimising NLL of the true label under softmax(logp / T)."""
    best, best_t = float("inf"), 1.0
    for t in [x / 10 for x in range(1, 51)] + [6.0, 8.0, 10.0, 15.0, 20.0]:
        nll = 0.0
        for r in rows:
            p = _softmax(r["logp"], t)[OPTIONS.index(r["y"])]
            nll -= math.log(max(p, 1e-12))
        if nll < best:
            best, best_t = nll, t
    return best_t


def probs_for(r: dict, method: str, t: float) -> list[float]:
    if method == "vote":
        return r["vote"]
    if method == "logit":
        return _softmax(r["logp"], 1.0)
    return _softmax(r["logp"], t)


# ---- metrics -----------------------------------------------------------------------------------------------


def _right(r: dict, pred: str) -> bool:
    return pred in (r["y"], r["alt"])


def auroc(pairs: list[tuple[float, bool]]) -> float | None:
    pos = [c for c, ok in pairs if ok]
    neg = [c for c, ok in pairs if not ok]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def ece(pairs: list[tuple[float, bool]], bins: int = 10) -> float:
    """Expected calibration error: |accuracy - mean confidence| per confidence bin, weighted by bin size."""
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        rs = [(c, ok) for c, ok in pairs if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if rs:
            acc = sum(ok for _, ok in rs) / len(rs)
            conf = sum(c for c, _ in rs) / len(rs)
            total += len(rs) / len(pairs) * abs(acc - conf)
    return total


def _quantile(scores: list[float], alpha: float) -> float:
    """The conformal quantile: the ceil((n+1)(1-alpha))-th smallest score, or +inf when n is too small."""
    n = len(scores)
    k = math.ceil((n + 1) * (1 - alpha))
    if k > n:
        return float("inf")
    return sorted(scores)[k - 1]


def cross_conformal(rows: list[dict], method: str, alpha: float, folds: int, seed: int = 0) -> dict:
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    fold_of = {i: k % folds for k, i in enumerate(order)}
    out = []
    temps = []
    for f in range(folds):
        cal = [rows[i] for i in range(len(rows)) if fold_of[i] != f]
        test = [rows[i] for i in range(len(rows)) if fold_of[i] == f]
        t = 1.0
        if method == "logit/T":
            half = len(cal) // 2
            t = _fit_temperature(cal[:half])
            cal = cal[half:]
            temps.append(t)
        q = _quantile([1 - probs_for(r, method, t)[OPTIONS.index(r["y"])] for r in cal], alpha)
        for r in test:
            p = probs_for(r, method, t)
            pset = [o for o, pi in zip(OPTIONS, p, strict=True) if 1 - pi <= q]
            top = OPTIONS[max(range(len(OPTIONS)), key=p.__getitem__)]
            out.append({"id": r["id"], "y": r["y"], "alt": r["alt"], "set": pset, "top": top, "conf": max(p)})
    n = len(out)
    covered = sum(1 for o in out if o["y"] in o["set"] or (o["alt"] and o["alt"] in o["set"]))
    singles = [o for o in out if len(o["set"]) == 1]
    single_wrong = sum(1 for o in singles if not _right(o, o["set"][0]))
    empties = sum(1 for o in out if not o["set"])
    pairs = [(o["conf"], _right(o, o["top"])) for o in out]
    by_class = {}
    for y in OPTIONS:
        rs = [o for o in out if o["y"] == y]
        if rs:
            by_class[y] = (sum(1 for o in rs if o["y"] in o["set"] or (o["alt"] and o["alt"] in o["set"])), len(rs))
    return {
        "n": n,
        "top1_acc": sum(ok for _, ok in pairs) / n,
        "auroc": auroc(pairs),
        "ece": ece(pairs),
        "coverage": covered / n,
        "mean_size": sum(len(o["set"]) for o in out) / n,
        "singletons": len(singles),
        "singleton_wrong": single_wrong,
        "empty": empties,
        "by_class": by_class,
        "temps": temps,
        "singleton_misses": [f"{o['id']}: set={o['set']} expected {o['y']}" for o in singles if not _right(o, o["set"][0])],
    }


# ---- report ------------------------------------------------------------------------------------------------


def report(provider: str, alphas: list[float], folds: int) -> None:
    rows = _load(provider)
    if not rows:
        print(f"{provider}: no scored, labeled rows in {run.results_path(provider).name}")
        return
    print(f"\n== {provider} on {run.SET} — {len(rows)} labeled letters, {folds}-fold cross-conformal")
    print(f"   label mix: {dict(Counter(r['y'] for r in rows))}")
    print("\n  method    top-1 acc   AUROC    ECE   | alpha  coverage  mean set  singletons (wrong)  empty")
    for method in ("vote", "logit", "logit/T"):
        first = True
        for alpha in alphas:
            s = cross_conformal(rows, method, alpha, folds)
            head = f"  {method:<9} {s['top1_acc']:>7.2f}   {s['auroc'] if s['auroc'] is not None else float('nan'):>5.2f}  {s['ece']:>5.2f}   |" if first else f"  {'':<9} {'':>7}   {'':>5}  {'':>5}   |"
            print(f"{head} {alpha:<6} {s['coverage']:>7.2f}  {s['mean_size']:>8.2f}  {s['singletons']:>4}/{s['n']:<4} ({s['singleton_wrong']:>2})    {s['empty']:>3}")
            first = False
        if method == "logit/T" and s["temps"]:
            ts = sorted(s["temps"])
            print(f"            fitted T per fold: median {ts[len(ts) // 2]:.1f}, range {ts[0]:.1f}–{ts[-1]:.1f}")
    # per-class coverage at the first alpha, for the method that matters
    alpha = alphas[0]
    print(f"\n  coverage by true class at alpha={alpha} (covered/n):")
    for method in ("vote", "logit/T"):
        s = cross_conformal(rows, method, alpha, folds)
        print(f"  {method:<9} " + "  ".join(f"{y}={c}/{n}" for y, (c, n) in s["by_class"].items()))
    s = cross_conformal(rows, "logit/T", alpha, folds)
    for m in s["singleton_misses"]:
        print("   singleton miss (logit/T):", m)


def main(argv: list[str]) -> None:
    alphas = [0.05, 0.1, 0.2]
    folds = 10
    if "--set" in argv:
        i = argv.index("--set")
        run.select_set(argv[i + 1])
        del argv[i : i + 2]
    if "--alpha" in argv:
        i = argv.index("--alpha")
        alphas = [float(argv[i + 1])]
        del argv[i : i + 2]
    if "--folds" in argv:
        i = argv.index("--folds")
        folds = int(argv[i + 1])
        del argv[i : i + 2]
    for provider in argv or ["score"]:
        report(provider, alphas, folds)


if __name__ == "__main__":
    main(sys.argv[1:])
