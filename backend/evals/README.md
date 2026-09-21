# Triage evals

`python -m evals.run stub gemini claude` scores each provider on the labeled set in `letters.py` and writes
`results-<provider>.jsonl`. `--rescore` re-scores a saved file against the current labels without API calls.

## The set

42 synthetic letters in three tiers. Synthetic because there is no public corpus of borrower letters (the
CFPB complaint database no longer exposes narratives); labeled by construction, with a `note` on every letter
whose label needs a reason.

| Tier | n | What it tests |
|---|---|---|
| plain | 20 | One thing per letter, one category each: (b)(1)–(b)(11), RFI owner/other, payoff, loss mit, not covered |
| trap | 8 | Mailroom reality: no loan number, two asks, OCR noise, payoff inside an RFI, a question that is not an error |
| hard | 14 | Where the label needs an argument, where the schema is the limit, or where two answers are defensible (`alt_case_type`) |

The hard tier was added after the first 28 scored 28/28 on Gemini. A set the model aces measures the set.

## What is scored

- `type_acc` — case type; `alt_case_type` hits are counted and reported separately
- `category_acc_given_type` — (b)(n) or RFI category, on letters where the type was right (it sets the clock)
- `loan_recovered` / `loan_not_invented` — the loan identifier when present; `null` when absent
- `exceptions_flagged` — expected flags are a subset of returned flags (`A|B` = either counts)
- `quotes_verbatim` — every `source_quote` appears in the letter, whitespace-insensitive. This is the metric
  behind rule 1 of the README: a value with no quote, or a "corrected" quote, is an invented value.

## Results — gemini-3.1-flash-lite, 42 letters

| | round 1 | round 2 | round 3 |
|---|---|---|---|
| change | hard tier added | prompt: origination ≠ servicing error; UNTIMELY needs payoff/transfer + a year | receipt date passed to the model |
| type_acc | 39/42 (+2 alt) | 39/42 (+2 alt) | 39/42 (+2 alt) |
| by tier | plain 20/20 · trap 8/8 · hard 13/14 | 20/20 · **7/8** · 14/14 | 20/20 · 7/8 · 14/14 |
| category given type | 30/30 | 29/29 | 29/29 |
| loan recovered / not invented | 38/38 · 4/4 | 38/38 · 4/4 | 37/38 · 4/4 |
| exceptions flagged | 3/5 | 4/5 | 4/5 |
| quotes verbatim | 42/42 | 42/42 | 42/42 |

Stub (keyword rules, no model): 21/42, hard tier 5/14. It exists so the pipeline runs without a key, and the
gap is the argument for using a model at all.

## What the misses say

**`hard-rate-complaint` (round 1 → fixed in round 2).** "This is wrong and I think there was an error when I
signed" → NOE (b)(11). Origination is not servicing (comment 35(b)-2), but the prompt never said so. One
sentence fixed it.

**`trap-overbroad` (regressed in round 2).** "This whole loan has been a nightmare … I want everything looked
at and fixed" went from NOE (b)(11) + OVERBROAD to NOT_COVERED + OVERBROAD. The sentence that fixed the rate
complaint ("general complaints without an asserted error are not covered") pulled this one over the line. The
model still flags OVERBROAD, so the operator still sees it — but the right route is an NOE that gets a
§1024.35(g)(2) exception letter, not a discard. **Every prompt change is a trade; the eval is what makes the
trade visible.** Not chased further: fixing it with another sentence is exactly the loop that produces a
2,000-word prompt nobody can reason about.

**`hard-untimely-old-loan` (open).** "Paid off March 2024", received October 2026, and the model does not
flag UNTIMELY — not in round 2 (rule clarified) and not in round 3 (date supplied). The letter says
everything needed. Two readings: flash-lite does not do the date arithmetic, or "I want it corrected" reads
strongly enough as an active dispute that the flag feels wrong to it. Either way the operator is the
backstop, which is why the flag is a *candidate* — but it is the one miss that could cost a clock.

**`hard-denial-appeal`, `hard-question-that-is-an-error` (alt ok).** The model chose NOE where the label says
LOSS_MIT / RFI. Both are defensible; the labels carry the argument in their `note`. What matters is that in
neither case does the model's choice lose a deadline the label's choice would keep — except that a
§1024.41(h) appeal has a 14-day window the NOE route does not surface, which is the reason LOSS_MIT is the
primary label.

**`hard-both-noe-and-rfi`.** Correct as NOE (b)(2), but the RFI half — its own 30-day clock — is not in the
proposal because `case_type` holds one value. **This is a schema miss, not a model miss.** The fix is a
`secondary_requests` list on the proposal and a second case opened on approval; it is not done because the
state machine keys one case to one correspondence, and that assumption is worth breaking on purpose, not as
a side effect.

**`hard-ocr-loan-digits`.** The model quoted `5S1O-22O-99E1` as-is rather than "fixing" it to digits.
That is the behaviour the verbatim check exists to protect: the operator sees the OCR error next to the
scan and corrects it; a model that silently corrected it would have produced a plausible, unverifiable number.

## Confidence is not information

Across 42 letters the model's self-reported `confidence` was never below 0.90. The three type misses carried
0.95, 1.00 and 0.95; the mean on hits was 0.99. A number that is 0.95 when wrong and 0.99 when right cannot
drive anything — not a review queue, not a threshold, not a dashboard. The UI shows it; nothing acts on it.

The honest fix is a calibrated probability from a model that produces one — a decision model that returns a
distribution over `case_type` rather than a token stream and a guess — and the decision/extraction split that
implies: a probabilistic classifier for the enumerated fields (type, category, flags), the LLM for the quoted
extractions only. That is the next experiment, keyed on access to such a model.

## Vote share instead of self-report (`votes.py`)

Same 42 letters, each sampled **5 times at temperature 1.0** (210 calls, ~40 min on the free tier with 429
backoff); the winning case type's vote share is the probability. `python -m evals.votes 5`:

| vote share | letters | majority right | mean self-reported confidence |
|---|---|---|---|
| 5/5 | 41 | 41 | 0.987 |
| 4/5 | 1 | **0** | 0.910 |

Majority-vote accuracy 41/42 (plain 20/20 · trap 7/8 · hard 14/14 with alternates). The one letter the
samples disagreed on — `trap-overbroad`, 4× NOT_COVERED, 1× NOE — is the one letter the majority got wrong.

Three honest readings:

1. **The signal is real and it is one data point.** On this set, "not unanimous" and "wrong" are the same
   letter. That is what a usable confidence looks like — a review queue keyed on *any disagreement* would
   have caught the miss — but a bucket with n=1 is a hint, not a calibration curve.
2. **flash-lite at temperature 1 is nearly deterministic here.** 41 unanimous out of 42 means the sampling
   has almost no resolution: it cannot say 0.7 vs 0.9, only "sure" vs "not sure". Finer probabilities need
   either perturbation (paraphrased letters, shuffled option order) or a model that outputs a distribution
   directly — the decision-model experiment, still keyed on access.
3. **Self-report was not entirely blind either.** Across 210 samples the lowest confidence the model ever
   wrote was 0.85, on the NOE sample of `trap-overbroad`; the letter's mean, 0.91, is the lowest of the 42.
   But `not-covered-coupon` and `hard-informal-owner` (both right, 5/5) sit at 0.90 too, so a threshold that
   catches the miss also catches two correct letters. Vote share separates them; self-report does not.

Cost of the signal: 5× the model calls. For a desk that triages hundreds of letters a day on a free-tier
model that is a real cost; for one that triages dozens it is the cheapest calibration available.

## Reading the results file

One row per letter: `expected` (labels), `got` (type, category, loan value, exceptions, confidence, quotes).
`results-gemini-round1.jsonl` is kept so the round-1 → round-2 regression can be diffed. `results-votes.jsonl` holds every sample of the vote run.
