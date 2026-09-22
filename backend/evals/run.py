"""Score every triage provider against the labeled set. Usage: python -m evals.run [--rescore|--resume] [--set cfpb] [--only <ids.txt>] [stub gemini score hybrid]

Reports, per provider: case-type accuracy (overall and per tier — plain / trap / hard), category accuracy on
the letters where the type was right, how often the loan identifier was recovered when present and *not*
invented when absent, whether flagged exceptions were flagged, and whether every `source_quote` is really in
the letter. Writes evals/results-<provider>.jsonl so individual misses can be read. Model providers cost API
calls — run them on purpose. `--rescore` re-scores a saved results file against the current labels.

Then, for every provider, whether its `confidence` means anything: accuracy per confidence band, and the
review-queue table — at each threshold, how many letters would be auto-routed and how many of those are wrong.
Providers that score (`score`, `hybrid`) also report position flips and prefill latency.

`--set cfpb` runs the real-narrative set instead (evals/cfpb.py): results go to results-cfpb-<provider>.jsonl,
labels come from cfpb/labels.jsonl, and the metrics that need labels the set does not have (loan identifier,
exceptions) are skipped. Conformal / temperature calibration on either set: `python -m evals.conformal`.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from servicing_desk.config import settings

from . import letters as _synthetic

HERE = Path(__file__).parent
LABEL_KEYS = ("case_type", "error_category", "rfi_category", "loan", "exceptions", "alt_case_type")  # exceptions: "A|B" = either
RECEIVED_ON = date(2026, 10, 15)  # fixed so timeliness labels stay stable

LETTERS: list[dict] = _synthetic.LETTERS
TEXT: dict[str, str] = {L["id"]: L["text"] for L in LETTERS}
ALL_IDS: set[str] = set(TEXT)  # every letter in the selected set, even when `restrict` narrows the run
SET = "synthetic"


def select_set(name: str) -> None:
    """Point the module at one letter set. `synthetic` (letters.py, gold labels) or `cfpb` (real narratives,
    labels from cfpb/labels.jsonl; unlabeled rows are run but not scored)."""
    global LETTERS, TEXT, SET, ALL_IDS
    if name == "cfpb":
        from .cfpb import load_letters

        LETTERS = load_letters()
    else:
        LETTERS = _synthetic.LETTERS
    TEXT = {L["id"]: L["text"] for L in LETTERS}
    ALL_IDS = set(TEXT)
    SET = name


def restrict(ids: set[str]) -> None:
    """Keep only these letters. Used for a second labeller's agreement subsample, which must be random."""
    global LETTERS, TEXT
    LETTERS = [L for L in LETTERS if L["id"] in ids]
    TEXT = {L["id"]: L["text"] for L in LETTERS}
    # ALL_IDS deliberately unchanged: a restricted run must not drop the results it is not responsible for.


def results_path(provider: str) -> Path:
    return HERE / (f"results-{provider}.jsonl" if SET == "synthetic" else f"results-{SET}-{provider}.jsonl")


def tier(letter_id: str) -> str:
    if letter_id.startswith("cfpb-"):
        return "cfpb"
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


def _run(provider: str, resume: bool = False) -> list[dict]:
    """Rows are appended to the results file as they are produced, so a run that dies on a quota (the free
    tier allows 500 requests a day and retries count) keeps what it paid for; `--resume` skips the letters
    already in the file and finishes the rest."""
    settings.triage_provider = provider
    from servicing_desk.triage import propose

    path = results_path(provider)
    rows = []
    if resume and path.exists():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        rows = [r for r in rows if r["id"] in ALL_IDS]  # drop letters removed from the set, keep the rest
    done = {r["id"] for r in rows}
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for L in LETTERS:
        if L["id"] in done:
            continue
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
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rows[-1]) + "\n")
        print(f"  {L['id']:<34} {d['case_type']:<15} {d['confidence']:.2f}", flush=True)
    return rows


def _cat(r: dict, side: str) -> str | None:
    ct = r["expected"]["case_type"]
    return r[side]["error_category"] if ct == "NOE" else r[side]["rfi_category"] if ct == "RFI" else None


def _score(rows: list[dict], full: bool = True) -> dict:
    """`full=False` (cfpb): the set has case-type / category labels only; the loan and exception metrics
    would be scored against nothing and are skipped."""
    rows = [r for r in rows if r["expected"]["case_type"]]  # unlabeled (open disagreement) rows are not scored
    n = len(rows)
    type_ok = [r for r in rows if r["got"]["case_type"] == r["expected"]["case_type"]]
    alt_ok = [r for r in rows if r not in type_ok and r["got"]["case_type"] == r["expected"].get("alt_case_type")]
    cat_applicable = [r for r in type_ok if r["expected"]["case_type"] in ("NOE", "RFI")]
    cat_applicable = [r for r in cat_applicable if _cat(r, "expected")]  # cfpb: category only where labellers agreed
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
    for t in ("plain", "trap", "hard") if full else ("cfpb",):
        rs = [r for r in rows if tier(r["id"]) == t]
        by_tier[t] = f"{sum(1 for r in rs if r in type_ok or r in alt_ok)}/{len(rs)}"
    misses = [
        f"{r['id']}: expected {r['expected']['case_type']}/{_cat(r, 'expected') or '-'}"
        f" got {r['got']['case_type']}/{r['got']['error_category'] or r['got']['rfi_category'] or '-'}"
        + (" [alt ok]" if r in alt_ok else "")
        for r in rows
        if r not in type_ok or (r in cat_applicable and r not in cat_ok)
    ]
    if full:
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
    } | (
        {}
        if full
        else dict.fromkeys(("loan_recovered", "loan_not_invented", "exceptions_flagged", "exceptions_not_invented"), "n/a (no labels on this set)")
    )


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
    rows = [r for r in rows if r["expected"]["case_type"]]
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
    resume = "--resume" in providers
    if "--set" in providers:
        i = providers.index("--set")
        select_set(providers[i + 1])
        del providers[i : i + 2]
    if "--only" in providers:  # restrict to the ids in a file, one per line (e.g. the agreement sample)
        i = providers.index("--only")
        keep = {line.strip() for line in (HERE / providers[i + 1]).read_text(encoding="utf-8").splitlines() if line.strip()}
        restrict(keep)
        del providers[i : i + 2]
    providers = [p for p in providers if p not in ("--rescore", "--resume")]
    for prov in providers:
        if rescore:  # re-score saved results against (possibly corrected) labels without new API calls
            saved = {json.loads(line)["id"]: json.loads(line) for line in results_path(prov).read_text(encoding="utf-8").splitlines() if line}
            rows = []
            for L in LETTERS:
                if L["id"] not in saved:
                    continue  # letter added after this results file was written
                saved[L["id"]]["expected"] = {k: L.get(k) for k in LABEL_KEYS}
                rows.append(saved[L["id"]])
        else:
            rows = _run(prov, resume=resume)
        s = _score(rows, full=SET == "synthetic")
        print(f"\n== {prov} ({rows[0]['model']}) — {s['n']} letters" + (f" [{SET}]" if SET != "synthetic" else ""))
        for k in ("type_acc", "type_acc_by_tier", "category_acc_given_type", "loan_recovered", "loan_not_invented", "exceptions_flagged", "exceptions_not_invented", "quotes_verbatim"):
            print(f"  {k:<26} {s[k]}")
        for m in s["misses"]:
            print("   miss:", m)
        print(f"\n-- is `confidence` information? ({prov})")
        _calibration(rows)


if __name__ == "__main__":
    main(sys.argv[1:] or ["stub"])
