"""Score every triage provider against the labeled set. Usage: python -m evals.run [--rescore] [stub gemini claude]

Reports, per provider: case-type accuracy, category accuracy on the letters where the type was right, how
often the loan identifier was recovered when present, and whether flagged exceptions were flagged. Writes
evals/results-<provider>.jsonl so individual misses can be read. Model providers cost API calls — run them
on purpose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from servicing_desk.config import settings

from .letters import LETTERS

HERE = Path(__file__).parent


def _run(provider: str) -> list[dict]:
    settings.triage_provider = provider
    from servicing_desk.triage import propose

    rows = []
    for L in LETTERS:
        p, model = propose(L["text"])
        d = p.model_dump()
        rows.append(
            {
                "id": L["id"],
                "model": model,
                "expected": {k: L.get(k) for k in ("case_type", "error_category", "rfi_category", "loan", "exceptions")},
                "got": {
                    "case_type": d["case_type"],
                    "error_category": d["error_category"],
                    "rfi_category": d["rfi_category"],
                    "loan": d["three_elements"]["loan_identifier"]["value"],
                    "exceptions": d["exception_candidates"],
                    "confidence": d["confidence"],
                },
            }
        )
    (HERE / f"results-{provider}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rows


def _score(rows: list[dict]) -> dict:
    n = len(rows)
    type_ok = [r for r in rows if r["got"]["case_type"] == r["expected"]["case_type"]]
    cat_applicable = [r for r in type_ok if r["expected"]["case_type"] in ("NOE", "RFI")]
    cat_ok = [
        r
        for r in cat_applicable
        if (r["got"]["error_category"] if r["expected"]["case_type"] == "NOE" else r["got"]["rfi_category"])
        == (r["expected"]["error_category"] if r["expected"]["case_type"] == "NOE" else r["expected"]["rfi_category"])
    ]
    loan_present = [r for r in rows if r["expected"]["loan"]]
    loan_ok = [r for r in loan_present if r["got"]["loan"]]
    loan_absent = [r for r in rows if not r["expected"]["loan"]]
    loan_null_ok = [r for r in loan_absent if not r["got"]["loan"]]  # did not invent one
    exc_expected = [r for r in rows if r["expected"]["exceptions"]]
    exc_ok = [r for r in exc_expected if set(r["expected"]["exceptions"]) <= set(r["got"]["exceptions"])]
    return {
        "n": n,
        "type_acc": f"{len(type_ok)}/{n}",
        "category_acc_given_type": f"{len(cat_ok)}/{len(cat_applicable)}",
        "loan_recovered": f"{len(loan_ok)}/{len(loan_present)}",
        "loan_not_invented": f"{len(loan_null_ok)}/{len(loan_absent)}",
        "exceptions_flagged": f"{len(exc_ok)}/{len(exc_expected)}",
        "misses": [
            f"{r['id']}: expected {r['expected']['case_type']}/{r['expected']['error_category'] or r['expected']['rfi_category'] or '-'}"
            f" got {r['got']['case_type']}/{r['got']['error_category'] or r['got']['rfi_category'] or '-'}"
            for r in rows
            if r not in type_ok or (r in cat_applicable and r not in cat_ok)
        ],
    }


def main(providers: list[str]) -> None:
    rescore = "--rescore" in providers
    providers = [p for p in providers if p != "--rescore"]
    for prov in providers:
        if rescore:  # re-score saved results against (possibly corrected) labels without new API calls
            saved = {json.loads(line)["id"]: json.loads(line) for line in (HERE / f"results-{prov}.jsonl").read_text(encoding="utf-8").splitlines() if line}
            for L in LETTERS:
                saved[L["id"]]["expected"] = {k: L.get(k) for k in ("case_type", "error_category", "rfi_category", "loan", "exceptions")}
            rows = [saved[L["id"]] for L in LETTERS]
        else:
            rows = _run(prov)
        s = _score(rows)
        print(f"\n== {prov} ({rows[0]['model']}) — {s['n']} letters")
        for k in ("type_acc", "category_acc_given_type", "loan_recovered", "loan_not_invented", "exceptions_flagged"):
            print(f"  {k:<26} {s[k]}")
        for m in s["misses"]:
            print("   miss:", m)


if __name__ == "__main__":
    main(sys.argv[1:] or ["stub"])
