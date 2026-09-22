"""A second, real set: consumer narratives from the CFPB Consumer Complaint Database, product = Mortgage.

`letters.py` is synthetic by necessity — the CFPB stopped publishing narratives in 2025 and the current bulk
CSV has no narrative column at all. But the 2015–2024 narratives were published and are mirrored on the
Hugging Face Hub (`BEE-spoke-data/consumer-finance-complaints`, a straight copy of the old CSV). They are
public-domain US government data, consumer-consented, with names, dates and amounts redacted (`XXXX`,
`{$2000.00}`).

They are not letters to a servicer — they are complaints *about* a servicer, written to a regulator, usually
after the letter to the servicer failed. The register differs (third person, a history rather than one ask),
which is exactly why they are worth having: the synthetic set measures the traps we thought of; this set
measures the prose we did not.

There is no ground truth. `labels.jsonl` is built by `python -m evals.cfpb labels`: one labeller read all
300 (`labels-second.jsonl`), a second labeller covered a random 60 (`agreement-sample.txt`), and the
disagreements were ruled on in `adjudicated.jsonl` with the rule cited each time. Every row records which
of the three it came from. See README "Round 5".

Usage:
  python -m evals.cfpb sample --parquet <shard.parquet> [--n 300] [--seed 0]   -> cfpb/letters.jsonl
  python -m evals.cfpb agreement [--n 60] [--seed 1]                          -> cfpb/agreement-sample.txt
  python -m evals.cfpb labels                                                 -> cfpb/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).parent / "cfpb"
LETTERS_PATH = HERE / "letters.jsonl"
LABELS_PATH = HERE / "labels.jsonl"
AGREEMENT_PATH = HERE / "agreement-sample.txt"
SOURCE = "BEE-spoke-data/consumer-finance-complaints (Hugging Face mirror of the CFPB Consumer Complaint Database)"
MIN_CHARS, MAX_CHARS = 300, 2500  # p10 of the pool is ~420, p90 ~3100; the cap keeps 20 prefills per letter cheap


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def load_letters() -> list[dict]:
    """Rows shaped like `letters.LETTERS` (id, text, plus CFPB metadata); labels merged in when present."""
    rows = _read_jsonl(LETTERS_PATH)
    if LABELS_PATH.exists():
        labels = {r["id"]: r for r in _read_jsonl(LABELS_PATH)}
        for r in rows:
            r.update({k: v for k, v in labels.get(r["id"], {}).items() if k != "id"})
    return rows


def sample(parquet: Path, n: int, seed: int) -> list[dict]:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    cols = ["Date received", "Product", "Issue", "Sub-issue", "Consumer complaint narrative", "Complaint ID", "Company"]
    t = pq.read_table(parquet, columns=cols)
    t = t.filter(pc.equal(t["Product"], "Mortgage"))
    t = t.filter(pc.is_valid(t["Consumer complaint narrative"]))
    pool = [
        r
        for r in t.to_pylist()
        if MIN_CHARS <= len(r["Consumer complaint narrative"]) <= MAX_CHARS
    ]
    # Proportional to the pool, not stratified: the point of the set is the distribution nobody designed.
    rng = random.Random(seed)
    picked = rng.sample(pool, n)
    picked.sort(key=lambda r: str(r["Complaint ID"]))
    return [
        {
            "id": f"cfpb-{r['Complaint ID']}",
            "text": r["Consumer complaint narrative"].strip(),
            "received": str(r["Date received"])[:10],
            "issue": r["Issue"],
            "sub_issue": r["Sub-issue"],
            "company": r["Company"],
        }
        for r in picked
    ]


def agreement_sample(n: int, seed: int) -> list[str]:
    """The ids a second labeller should cover to estimate agreement. Random, because `letters.jsonl` is
    ordered by complaint id — which is chronological, so the first N letters are the oldest N and an
    agreement figure computed on them describes 2015, not the set."""
    ids = [r["id"] for r in _read_jsonl(LETTERS_PATH)]
    picked = random.Random(seed).sample(ids, min(n, len(ids)))
    return sorted(picked)


def build_labels() -> list[dict]:
    """Merge the two labellers. Agreement -> label with source=agree; disagreement -> the adjudicated answer
    from adjudicated.jsonl if present, else the row is left unlabeled (source=open) and skipped by the evals."""
    gem_path = HERE / "labels-gemini.jsonl"
    gem = {r["id"]: r for r in _read_jsonl(gem_path)} if gem_path.exists() else {}
    sec = {r["id"]: r for r in _read_jsonl(HERE / "labels-second.jsonl")}
    adj_path = HERE / "adjudicated.jsonl"
    adj = {r["id"]: r for r in _read_jsonl(adj_path)} if adj_path.exists() else {}
    out = []
    for r in _read_jsonl(LETTERS_PATH):
        i = r["id"]
        g, s = gem.get(i), sec.get(i)
        if not s:
            continue
        row = {"id": i}
        if not g:  # Gemini pass not run yet: one labeller, and the file says so
            row.update({k: s.get(k) for k in ("case_type", "error_category", "rfi_category") if s.get(k)}, source="second-only")
        elif g["case_type"] == s["case_type"]:
            row.update(case_type=g["case_type"], source="agree")
            cat = "error_category" if g["case_type"] == "NOE" else "rfi_category" if g["case_type"] == "RFI" else None
            if cat:
                row[cat] = g[cat] if g.get(cat) == s.get(cat) else None  # category only when both agree
        elif i in adj:
            row.update({k: v for k, v in adj[i].items() if k not in ("id", "ruling")}, source="adjudicated")
        else:
            row.update(case_type=None, source="open", gemini=g["case_type"], second=s["case_type"])
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--parquet", type=Path, required=True)
    s.add_argument("--n", type=int, default=300)
    s.add_argument("--seed", type=int, default=0)
    a = sub.add_parser("agreement")
    a.add_argument("--n", type=int, default=60)
    a.add_argument("--seed", type=int, default=1)
    sub.add_parser("labels")
    a = ap.parse_args()
    if a.cmd == "sample":
        rows = sample(a.parquet, a.n, a.seed)
        _write_jsonl(LETTERS_PATH, rows)
        from collections import Counter

        print(f"{len(rows)} letters -> {LETTERS_PATH}")
        for k, v in Counter(r["issue"] for r in rows).most_common():
            print(f"  {v:>4}  {k}")
    elif a.cmd == "agreement":
        ids = agreement_sample(a.n, a.seed)
        AGREEMENT_PATH.write_text("\n".join(ids) + "\n", encoding="utf-8")
        print(f"{len(ids)} ids -> {AGREEMENT_PATH}")
        print("  python -m evals.run --set cfpb --only cfpb/agreement-sample.txt --resume gemini")
    else:
        rows = build_labels()
        _write_jsonl(LABELS_PATH, rows)
        from collections import Counter

        c = Counter(r["source"] for r in rows)
        print(f"{len(rows)} rows -> {LABELS_PATH}: {dict(c)}")
        for r in rows:
            if r["source"] == "open":
                print(f"  open: {r['id']}  gemini={r['gemini']}  second={r['second']}")


if __name__ == "__main__":
    main()
