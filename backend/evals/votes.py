"""Confidence by voting instead of self-report. Usage: python -m evals.votes [N] [--rescore]

The model's own `confidence` field never dropped below 0.90 on this set, including on its misses (see
README.md). This asks a different question: sample the same letter N times at temperature 1 and take the
vote share of the winning case type as the probability. A vote share is an empirical number — if 5/5 letters
are right more often than 3/5 letters, the number can drive a review queue; a self-report cannot.

Writes results-votes.jsonl (one row per letter with every sample) and prints a calibration table:
vote share bucket → how many letters, how many the majority got right, mean self-reported confidence.
Costs N model calls per letter; run it on purpose. `--rescore` re-tabulates a saved run.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from servicing_desk.config import settings

from .letters import LETTERS
from .run import RECEIVED_ON, tier

HERE = Path(__file__).parent
OUT = HERE / "results-votes.jsonl"


def _sample(n: int) -> list[dict]:
    from servicing_desk.triage.gemini import propose

    rows = []
    for L in LETTERS:
        samples = []
        for _ in range(n):
            p, model = propose(L["text"], received_on=RECEIVED_ON, temperature=1.0)
            samples.append({"case_type": p.case_type, "category": p.error_category or p.rfi_category, "confidence": p.confidence})
        rows.append({"id": L["id"], "model": model, "expected": L["case_type"], "alt": L.get("alt_case_type"), "samples": samples})
        (OUT).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")  # progress survives a crash
        print(f"  {L['id']:<34} {Counter(s['case_type'] for s in samples).most_common()}", flush=True)
    return rows


def tabulate(rows: list[dict]) -> None:
    n = len(rows[0]["samples"])
    per = []
    for r in rows:
        votes = Counter(s["case_type"] for s in r["samples"])
        winner, k = votes.most_common(1)[0]
        ok = winner == r["expected"] or (r["alt"] is not None and winner == r["alt"])
        per.append({"id": r["id"], "share": k / n, "winner": winner, "ok": ok, "self": statistics.mean(s["confidence"] for s in r["samples"]), "votes": dict(votes)})

    print(f"\n== vote-share calibration, {len(rows)} letters × {n} samples (temperature 1.0)")
    print(f"  {'vote share':<12} {'letters':>7} {'majority right':>15} {'accuracy':>9} {'mean self-conf':>15}")
    buckets = sorted({p['share'] for p in per}, reverse=True)
    for b in buckets:
        ps = [p for p in per if p["share"] == b]
        right = sum(p["ok"] for p in ps)
        print(f"  {int(b * n)}/{n:<10} {len(ps):>7} {right:>15} {right / len(ps):>9.2f} {statistics.mean(p['self'] for p in ps):>15.3f}")
    print(f"\n  majority-vote accuracy: {sum(p['ok'] for p in per)}/{len(per)}")
    print("  by tier: " + "  ".join(f"{t}={sum(p['ok'] for p in per if tier(p['id']) == t)}/{sum(1 for p in per if tier(p['id']) == t)}" for t in ("plain", "trap", "hard")))
    split = [p for p in per if p["share"] < 1]
    print(f"\n  letters where the samples disagreed ({len(split)}):")
    for p in sorted(split, key=lambda p: p["share"]):
        print(f"   {p['id']:<34} {p['votes']}  majority {'ok' if p['ok'] else 'WRONG'}  self-conf {p['self']:.2f}")


def main(argv: list[str]) -> None:
    rescore = "--rescore" in argv
    argv = [a for a in argv if a != "--rescore"]
    if rescore:
        rows = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line]
    else:
        settings.triage_provider = "gemini"
        rows = _sample(int(argv[0]) if argv else 5)
    tabulate(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
