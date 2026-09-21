"""Score every triage provider against the labeled set. Usage: python -m evals.run [--rescore] [stub gemini score hybrid]

Reports, per provider: case-type accuracy (overall and per tier — plain / trap / hard), category accuracy on
the letters where the type was right, how often the loan identifier was recovered when present and *not*
invented when absent, whether flagged exceptions were flagged, and whether every `source_quote` is really in
the letter. Writes evals/results-<provider>.jsonl so individual misses can be read. Model providers cost API
calls — run them on purpose. `--rescore` re-scores a saved results file against the current labels.

Then, for every provider, whether its `confidence` means anything: accuracy per confidence band, and the
review-queue table — at each threshold, how many letters would be auto-routed and how many of those are wrong.
Providers that score (`score`, `hybrid`) also report position flips and prefill latency.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from servicing_desk.config import settings

from .letters import LETTERS

HERE = Path(__file__).parent
LABEL_KEYS = ("case_type", "error_category", "rfi_category", "loan", "exceptions", "alt_case_type")  # exceptions: "A|B" = either
TEXT = {L["id"]: L["text"] for L in LETTERS}
RECEIVED_ON = date(2026, 10, 15)  # fixed so timeliness labels stay stable


def tier(letter_id: str) -> str:
    return letter_id.split("-", 1)[0] if letter_id.startswith(("trap-", "hard-")) else "plain"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _quotes(d: dict) -> list[str]:
    e = d["three_elements"]
    qs = [e[k]["source_quote"] for k in ("borrower_name", "loan_identifier", "assertion_or_request")]
    qs.append(d["mentions_foreclosure_sale_date"]["source_quote"])
    return [q for q in qs if q]


def _not_verbatim(letter_id: str, quotes: list[str]) -> list[str]:
    return [q for q in quotes if _norm(q) not in _norm(TEXT[letter_id])]


def _run(provider: str) -> list[dict]:
    settings.triage_provider = provider
    from servicing_desk.triage import propose

    rows = []
    for L in LETTERS:
        p, model = propose(L["text"], received_on=RECEIVED_ON)
        d = p.model_dump()
        rows.append(
            {
                "id": L["id"],
                "model": model,
                "expected": {k: L.get(k) for k in LABEL_KEYS},
                "got": {
                    "case_type": d["case_type"],
                    "error_category": d["error_category"],
                    "rfi_category": d["rfi_category"],
                    "loan": d["three_elements"]["loan_identifier"]["value"],
                    "exceptions": d["exception_candidates"],
                    "confidence": d["confidence"],
                    "quotes": _quotes(d),
                    "scores": getattr(p, "_scores", None),  # scoring providers: distributions + diagnostics
                },
            }
        )
        print(f"  {L['id']:<34} {d['case_type']:<15} {d['confidence']:.2f}", flush=True)
    (HERE / f"results-{provider}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rows


def _cat(r: dict, side: str) -> str | None:
    ct = r["expected"]["case_type"]
    return r[side]["error_category"] if ct == "NOE" else r[side]["rfi_category"] if ct == "RFI" else None


def _score(rows: list[dict]) -> dict:
    n = len(rows)
    type_ok = [r for r in rows if r["got"]["case_type"] == r["expected"]["case_type"]]
    alt_ok = [r for r in rows if r not in type_ok and r["got"]["case_type"] == r["expected"].get("alt_case_type")]
    cat_applicable = [r for r in type_ok if r["expected"]["case_type"] in ("NOE", "RFI")]
    cat_ok = [r for r in cat_applicable if _cat(r, "got") == _cat(r, "expected")]
    loan_present = [r for r in rows if r["expected"]["loan"]]
    loan_ok = [r for r in loan_present if r["got"]["loan"]]
    loan_absent = [r for r in rows if not r["expected"]["loan"]]
    loan_null_ok = [r for r in loan_absent if not r["got"]["loan"]]  # did not invent one
    exc_expected = [r for r in rows if r["expected"]["exceptions"]]
    exc_ok = [r for r in exc_expected if all(set(e.split("|")) & set(r["got"]["exceptions"]) for e in r["expected"]["exceptions"])]
    # the other direction: a flag the label does not allow is noise the operator has to clear
    exc_allowed = lambda r: {e for x in (r["expected"]["exceptions"] or []) for e in x.split("|")}  # noqa: E731
    exc_clean = [r for r in rows if set(r["got"]["exceptions"]) <= exc_allowed(r)]
    quoted = [r for r in rows if "quotes" in r["got"]]  # results written before the check have no quotes
    quoted_ok = [r for r in quoted if not _not_verbatim(r["id"], r["got"]["quotes"])]
    by_tier = {}
    for t in ("plain", "trap", "hard"):
        rs = [r for r in rows if tier(r["id"]) == t]
        by_tier[t] = f"{sum(1 for r in rs if r in type_ok or r in alt_ok)}/{len(rs)}"
    misses = [
        f"{r['id']}: expected {r['expected']['case_type']}/{_cat(r, 'expected') or '-'}"
        f" got {r['got']['case_type']}/{r['got']['error_category'] or r['got']['rfi_category'] or '-'}"
        + (" [alt ok]" if r in alt_ok else "")
        for r in rows
        if r not in type_ok or (r in cat_applicable and r not in cat_ok)
    ]
    misses += [f"{r['id']}: exceptions expected {r['expected']['exceptions']} got {r['got']['exceptions']}" for r in exc_expected if r not in exc_ok]
    misses += [f"{r['id']}: quote not in letter: {_not_verbatim(r['id'], r['got']['quotes'])}" for r in quoted if r not in quoted_ok]
    return {
        "n": n,
        "type_acc": f"{len(type_ok)}/{n}" + (f" (+{len(alt_ok)} via alt)" if alt_ok else ""),
        "type_acc_by_tier": "  ".join(f"{t}={v}" for t, v in by_tier.items()),
        "category_acc_given_type": f"{len(cat_ok)}/{len(cat_applicable)}",
        "loan_recovered": f"{len(loan_ok)}/{len(loan_present)}",
        "loan_not_invented": f"{len(loan_null_ok)}/{len(loan_absent)}",
        "exceptions_flagged": f"{len(exc_ok)}/{len(exc_expected)}",
        "exceptions_not_invented": f"{len(exc_clean)}/{n}",
        "quotes_verbatim": f"{len(quoted_ok)}/{len(quoted)}" if quoted else "n/a (results predate the check)",
        "misses": misses,
    }


def _right(r: dict) -> bool:
    return r["got"]["case_type"] in (r["expected"]["case_type"], r["expected"].get("alt_case_type"))


def _auroc(rows: list[dict]) -> float | None:
    """P(confidence on a right letter > confidence on a wrong one). 0.5 = the number carries nothing."""
    pos = [r["got"]["confidence"] for r in rows if _right(r)]
    neg = [r["got"]["confidence"] for r in rows if not _right(r)]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _calibration(rows: list[dict]) -> None:
    n = len(rows)
    print("  confidence band       letters   right   accuracy")
    for lo, hi in ((0.0, 0.7), (0.7, 0.9), (0.9, 0.99), (0.99, 1.01)):
        rs = [r for r in rows if lo <= r["got"]["confidence"] < hi]
        if rs:
            k = sum(_right(r) for r in rs)
            print(f"  [{lo:.2f}, {hi if hi <= 1 else 1.0:.2f}{')' if hi <= 1 else ']'}{'':<9}{len(rs):>5}{k:>8}{k / len(rs):>11.2f}")
    auroc = _auroc(rows)
    print(f"  AUROC(confidence -> right)  {auroc:.2f}" if auroc is not None else "  AUROC  n/a (no misses)")
    print("  auto-route if conf >=   covered   wrong among covered")
    for th in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        cov = [r for r in rows if r["got"]["confidence"] >= th]
        wrong = sum(not _right(r) for r in cov)
        print(f"  {th:<22} {len(cov):>3}/{n:<5} {wrong:>3}")
    scored = [r for r in rows if r["got"].get("scores")]
    if scored:
        flips = sum(r["got"]["scores"]["case_type"]["flips"] for r in scored)
        mass = sum(r["got"]["scores"]["case_type"]["label_mass"] for r in scored) / len(scored)
        lat = sorted(r["got"]["scores"]["latency_ms"] for r in scored)
        pre = sum(r["got"]["scores"]["prefills"] for r in scored) / len(scored)
        print(f"  position flips (case_type)  {flips} across {len(scored)} letters; mean label mass {mass:.3f}")
        print(f"  prefills/letter {pre:.0f}; scoring latency median {lat[len(lat) // 2]:.0f} ms, max {lat[-1]:.0f} ms")


def main(providers: list[str]) -> None:
    rescore = "--rescore" in providers
    providers = [p for p in providers if p != "--rescore"]
    for prov in providers:
        if rescore:  # re-score saved results against (possibly corrected) labels without new API calls
            saved = {json.loads(line)["id"]: json.loads(line) for line in (HERE / f"results-{prov}.jsonl").read_text(encoding="utf-8").splitlines() if line}
            rows = []
            for L in LETTERS:
                if L["id"] not in saved:
                    continue  # letter added after this results file was written
                saved[L["id"]]["expected"] = {k: L.get(k) for k in LABEL_KEYS}
                rows.append(saved[L["id"]])
        else:
            rows = _run(prov)
        s = _score(rows)
        print(f"\n== {prov} ({rows[0]['model']}) — {s['n']} letters")
        for k in ("type_acc", "type_acc_by_tier", "category_acc_given_type", "loan_recovered", "loan_not_invented", "exceptions_flagged", "exceptions_not_invented", "quotes_verbatim"):
            print(f"  {k:<26} {s[k]}")
        for m in s["misses"]:
            print("   miss:", m)
        print(f"\n-- is `confidence` information? ({prov})")
        _calibration(rows)


if __name__ == "__main__":
    main(sys.argv[1:] or ["stub"])
