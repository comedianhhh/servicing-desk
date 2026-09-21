# Triage evals

`python -m evals.run stub gemini claude score hybrid` scores each provider on the labeled set in `letters.py`
and writes `results-<provider>.jsonl`. `--rescore` re-scores a saved file against the current labels without
API calls. `score` and `hybrid` need a local `llama-server` (see "Scoring instead of generating").

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
- `exceptions_not_invented` — returned flags are a subset of the allowed ones; a flag the label does not
  permit is noise the operator has to clear (added in round 4, when a provider produced a lot of it)
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

## Scoring instead of generating (`score`, `hybrid`) — round 4

The previous section ended on "a model that outputs a distribution directly … still keyed on access". It is
not keyed on access. Any causal LM produces, at the position right after the prompt, one logit per vocabulary
token; if the allowed answers are single tokens, reading those logits and normalising them among themselves
*is* a distribution over the answers — no decoding, no JSON, one prefill. `triage/score.py` does this against
a local llama.cpp server (`llama-server` with `Qwen3-4B-Instruct-2507` Q8, 16 GB consumer GPU, no key):

1. Render `system + letter + question + "A = …, B = …"` through the model's own chat template
   (`/apply-template`), so the scored position is the first assistant token, not a guess at it.
2. Check each label is exactly one token (`/tokenize`; `A` is id 32, `\nA` is `[198, 32]` — the check exists
   because the difference is invisible in the prompt).
3. `/completion` with `n_predict=1, n_probs=20`; softmax over the label tokens only.
4. Repeat under 5 rotations of the option order and average. Small models prefer some letters; averaging over
   orders turns that into a measurable number (`flips`, below) instead of a hidden bias.

The enumerated fields — `case_type`, the (b)(n) / RFI category, each exception as a yes/no — come from
scoring; ~20 prefills per letter. The quoted extractions cannot come from scoring (the answers are not known
in advance) and stay with the stub (`score`) or Gemini (`hybrid`). `confidence` becomes the averaged top-1
probability of `case_type`.

### Results — Qwen3-4B-Instruct Q8 via llama.cpp, 42 letters

| | stub | gemini flash-lite | **score** |
|---|---|---|---|
| type_acc | 21/42 (+1 alt) | 39/42 (+2 alt) | **35/42 (+2 alt)** |
| by tier | 13/20 · 4/8 · 5/14 | 20/20 · 7/8 · 14/14 | **19/20 · 6/8 · 12/14** |
| category given type | 5/13 | 29/29 | **26/26** |
| exceptions flagged / not invented | 2/5 · 25/42 | 4/5 · 41/42 | **3/5 · 25/42** |
| model calls per letter | 0 | 1 generation (~2–4 s) | 20 prefills (~1 s, median 1017 ms) |

Position flips: 14 across 42 letters (a rotation whose winner differed from the averaged winner). Mean raw
probability mass on the label tokens: 1.000 — the model never wanted to say anything but a letter.

**Is the number information now?** Partly, and the way it fails is more instructive than the way it works.

| confidence band | letters | right | accuracy |
|---|---|---|---|
| [0.60, 0.70) | 1 | 1 | 1.00 |
| [0.70, 0.90) | 12 | 9 | 0.75 |
| [0.90, 0.99) | 1 | 1 | 1.00 |
| [0.99, 1.00] | 28 | 26 | 0.93 |

| auto-route if confidence ≥ | covered | wrong among covered |
|---|---|---|
| 0.80 | 38/42 | 5 |
| 0.90 | 29/42 | 2 |
| 0.99 | 28/42 | 2 |

AUROC (confidence separates right from wrong) 0.64 — against 0.50 for the stub and 0.90 for Gemini's
self-report (which, read against the alternates, is not as blind as the section above concluded from the
strict labels: it separates, but only at ≥ 0.99, with everything above 0.90).

1. **The distribution spreads for the first time.** Gemini's self-report never left [0.90, 1.00]; scoring
   puts 13 letters below 0.90, and 9 of them are right — the "send for review" band finally has letters in
   it. A threshold of 0.90 would auto-route 29 letters and queue 13, the shape a desk actually wants.
2. **Two misses are confidently wrong, and they are definitional.** `noe-b10-sale` (a foreclosure-sale
   error while in loss mitigation) scored LOSS_MIT at 1.00 in every rotation; `hard-rate-complaint` scored
   NOE at 1.00. No calibration fixes a model that is certain and wrong — that is the model's definition of
   the category disagreeing with the desk's, the same kind of miss the round-2 prompt sentence fixed for
   Gemini. Scoring gives a number the desk can act on *only* on letters the model is unsure about; it says
   nothing about letters it is sure and wrong about. The operator stays.
3. **The "probability" is a vote share in disguise.** Within one rotation the restricted softmax is almost
   always one-hot (0.80 = four orders said A, one said B). So what scoring measures on this model is the
   same thing `votes.py` measured by sampling Gemini five times — disagreement under perturbation — at five
   prefills instead of five generations, and with the perturbation (option order) chosen rather than random.
   The resolution is 1/5 per decision; more rotations or paraphrased letters would buy more.
4. **The binary flags are the weak point, and the eval had no metric for it.** Asked "is this letter
   OVERBROAD?", the 4B model says yes on 15 of 42 letters, including `payoff-plain` and `rfi-owner`. The
   existing `exceptions_flagged` only checks that expected flags are present; 25/42 on the new
   `exceptions_not_invented` is what surfaced the noise (Gemini: 41/42). A yes/no framed as a single
   statement leans yes; the fix is to score each flag as a choice among "present / not present / cannot
   tell from the letter", or to raise the threshold per flag from labeled data — and to keep the metric.

### What this buys and what it does not

Scoring is the right tool when the answer set is known and selection is all that is needed; it removes the
decode loop and gives a distribution the code can threshold. It does not remove the need for definitions
(the confident misses), for extraction (the quotes), or for the operator (everything the model is sure
about). What it changes for this desk: the review queue can be keyed on a number that is at least ordered,
and it costs one local GPU instead of an API key.

Not done, on purpose: the `hybrid` run (Gemini extraction + local decisions) has the same decisions as
`score` and only changes the extraction columns; a larger local model (8B) to see whether the definitional
misses are size or prompt; rotations > 5 for finer resolution. Each is one command once the numbers above
are worth improving on.

## Reading the results file

One row per letter: `expected` (labels), `got` (type, category, loan value, exceptions, confidence, quotes).
`results-gemini-round1.jsonl` is kept so the round-1 → round-2 regression can be diffed. `results-votes.jsonl` holds every sample of the vote run. Rows from `score`/`hybrid` carry `got.scores`: the averaged
distribution, `flips` and `label_mass` per decision, prefill count and latency.
