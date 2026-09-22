# Triage evals

`python -m evals.run stub gemini claude score hybrid jev` scores each provider on the labeled set in `letters.py`
and writes `results-<provider>.jsonl`; `--set cfpb` runs the real set instead. `--rescore` re-scores a
saved file against the current labels without API calls; `--resume` finishes an interrupted run. `score`
and `hybrid` need a local `llama-server` (see "Scoring instead of generating"). `python -m evals.conformal
[--set cfpb] score` turns a scored results file into calibration and conformal tables (round 5).

## The set

Two sets. `letters.py`: 42 synthetic letters in three tiers, labeled by construction, with a `note` on every
letter whose label needs a reason. `cfpb/letters.jsonl` (round 5): 300 real consumer narratives from the
CFPB complaint database, product = Mortgage, labeled after the fact — see "Round 5" for where they come
from and how the labels were made.

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

## Round 5 — real letters, and a number with a guarantee

Round 4 ended with a confidence that was *ordered* (AUROC 0.64) but not a probability, measured on 42
letters we wrote ourselves. Two things were missing: text nobody on this project composed, and a way to turn
an uncalibrated score into a routing decision with a stated error rate. This round adds both.

### The real set (`evals/cfpb.py`)

The CFPB stopped publishing complaint narratives in 2025 — the current bulk CSV has no narrative column —
but the 2015–2024 narratives are mirrored on the Hugging Face Hub (`BEE-spoke-data/consumer-finance-complaints`,
a straight copy of the old CSV; US-government public domain, consumer-consented, names/dates/amounts
redacted as `XXXX`). One 126 MB shard holds 672k complaints, 10,120 of them mortgage complaints with a
narrative. `python -m evals.cfpb sample` draws 300 at random (seed 0, 300–2,500 characters) —
proportional to the pool, not stratified, because the point is the distribution nobody designed: 46 %
"trouble during payment process", 19 % "struggling to pay", 20 % origination and closing, the rest escrow,
transfer, credit reporting.

These are not letters to a servicer. They are complaints *about* one, written to a regulator after the
letter to the servicer failed: third person, a history rather than a single ask, 1,300 characters on
median against 300 for the synthetic set. That is the value. The synthetic set measures the traps we thought
of; this one measures the prose we did not.

**Labels.** There is no ground truth, so one labeller read all 300 narratives and wrote a label with a
one-line reason each (`cfpb/labels-second.jsonl`), and a second labeller — the Gemini provider, working
blind from the same five definitions — covered a **random 60** of them (`cfpb/agreement-sample.txt`,
`python -m evals.cfpb agreement`). Sixty is the right size for an agreement estimate and all 300 is waste;
the first attempt got that wrong in a way worth recording. The results file is ordered by complaint id,
which is chronological, so an earlier partial pass had double-labeled the first 52 letters — all of them
2015–2018. The 75 % agreement computed on that prefix describes 2015, not this set. The random 60 spans
2015–2024 in the set's own proportions.

| | |
|---|---|
| agreement on case type | **47/60 = 78 %** (95 % CI 68–89 %) |
| Cohen's κ | **0.61** (substantial; chance agreement is high here because NOE is two-thirds of the set) |
| disagreements | 13, of which **10 are Gemini saying NOT_COVERED** where the first labeller said NOE (3), LOSS_MIT (4) or RFI (3) |

The disagreement is one boundary, not thirteen: when a complaint describes a servicing failure at length
without naming a specific error or asking for a specific thing, is it a notice of error, a loss-mitigation
request, or nothing the rule covers? That is also where the model under test makes most of its errors,
which is the useful part — the labellers disagree where the task is genuinely hard, not at random.

`python -m evals.cfpb labels` merges them: 47 `agree`, 13 `adjudicated`, 240 `second-only` (one careful
pass, which is what one careful pass buys and no more). Every row says which.

The 13 were ruled in `cfpb/adjudicated.jsonl`, each with the rule it turns on. **Ten kept labeller 1, three
were changed to Gemini's answer — and all three changes run the same way**: labeller 1 had called a letter
covered when the rule does not cover it. A request that the servicer join a voluntary state grant programme
is not a loss-mitigation request (no clock exists for it); a letter explaining why the borrower is slow to
finish paperwork requests nothing at all; and a denied *assumption* application is an underwriting decision,
which labeller 1's own stated rule puts outside servicing. One labeller leaned toward coverage, the other
away from it, and the ruling landed nearer the first — but not at it, and the three corrections are the
useful part of having a second pair of eyes at all.

The adjudicator was labeller 1, which is not independent and is recorded as such. Each ruling is one
sentence with its citation, so it can be overruled in the time it takes to read it; the labels rebuild with
`python -m evals.cfpb labels`.

The labeller's own boundary calls, recorded in the notes and worth knowing before reading the misses: a
complaint that both asserts a servicing error and asks for help was labeled by the assertion (NOE) unless
the only ask was a modification/forbearance/plan (LOSS_MIT); origination, underwriting, refinance and
closing complaints are NOT_COVERED even when they say "error"; HELOC complaints are labeled by the
schema's definitions although Reg X's servicing rules exclude open-end credit (noted per row); collection
calls inside the grace period with no false statement are NOT_COVERED, letters *falsely* stating a payment
is late are NOE (b)(11). Label mix: NOE 201, NOT_COVERED 48, LOSS_MIT 28, RFI 21, PAYOFF_REQUEST 2 —
(b)(11) "other" is 93 of the 201 NOEs, which is what a category list written for letters looks like
when applied to complaints.

### Results on the real set — 300 narratives

| | stub | **score** (Qwen3-4B, local) |
|---|---|---|
| type_acc | 145/300 (48 %) | **228/300 (76 %)** |
| category given type | 34/101 | 106/174 |
| quotes_verbatim | 300/300 | 300/300 |
| latency / letter | 0 | ~0.9 s (16 prefills) |

Gemini is not a column here. It is the second labeller, and scoring a labeller against the labels it helped
produce measures nothing. Its accuracy on this set can only be read after the 13 open rows are adjudicated
by someone who is neither labeller, and even then only on the 60 it saw.

The synthetic set said 83 %; the real set says 76 %, and the misses have a shape. Of the 72, 26 are
origination complaints (refinance denied, appraisal fee, closing delays) scored as NOE — "error" and
"wrong" in a letter about underwriting — and 24 are NOE↔LOSS_MIT, letters that describe a modification
going wrong. The first is a definitional miss the 4B model makes and the prompt already tries to prevent;
the second is partly label ambiguity (several of those the second labeller called NOE with LOSS_MIT as a
defensible alternative). Neither is fixed by calibration; calibration only tells you how much of the queue
you may not route.

### Flags first

Round 4's fourth reading — the yes/no flags lean yes, `exceptions_not_invented` 25/42 — had to be fixed
before any of the calibration below could be extended to the flags, and the real set showed how badly:
**191 of 300 narratives came back with at least one exception candidate, OVERBROAD on 167 (56 %)**. A
long complaint with many grievances "does not identify a specific error" if you squint, and a forced
binary squints. Three changes, measured one at a time on the synthetic set:

| | not invented | OVERBROAD flagged (2 true) | prefills / letter |
|---|---|---|---|
| round 4: yes / no | 25/42 | 15 | 20 |
| + third option "cannot tell from the letter" | 29/42 | 12 | 26 |
| + a longer OVERBROAD definition with a negation ("…is NOT overbroad") | 24/42 | 17, every one at p ≈ 0.67 with one order flipping | 16 |
| + judge exceptions only where the rule has them; short positive definition | **37/42** | **4** | **16** |

The row that went backwards is the instructive one. Spelling out the exception with a negation made the
4B model answer by option position: every letter scored 0.67 yes, two orders out of three, which is the
`flips` diagnostic doing its job. Small models do not read "NOT". The change that worked is structural
and comes from the regulation, not the prompt: the six exceptions exist only for notices of error
(§1024.35(g)(1): duplicative, overbroad, untimely) and requests for information (§1024.36(f)(1): all six).
Asking whether a hardship letter is an overbroad notice of error was half of round 4's noise. On the real
set the same change takes flagged letters from 191 to **12 of 300** (OVERBROAD 167 → 3, and the three
are "send me the entire loan file" requests), and the 12 read as an operator would want them: seven
DUPLICATIVE on letters that say "this is the third time", two UNTIMELY on loans the letter says were paid
off, one BURDENSOME on a repeat demand for every origination document. Accuracy on the enumerated fields is
unchanged (228/300; the case-type decision does not see the flags) and the letter costs four fewer prefills.

Still open on the flags: `hard-untimely-old-loan` needs the date arithmetic the prompt describes and the
model does not do; `hard-third-time-escrow` reads DUPLICATIVE as BURDENSOME; and a letter whose case type
is missed (trap-overbroad → NOT_COVERED) never gets its flags judged, which is the right cascade and still
a miss. Calibrating the flag probabilities the way case_type is calibrated below needs labels for them on
the real set, which the second labeller did not produce.

### Is the number a probability now? Three ways to read the same logits

`score` records, per decision, the restricted log-probabilities of every option under every rotation
(`got.scores.case_type.logp`, round 5). `python -m evals.conformal [--set cfpb] score` reads them three ways:

- **vote** — average the per-rotation probabilities (what round 4 called `confidence`). Each rotation is
  near one-hot, so this is the share of option orders that agreed: five rotations, six possible values.
- **logit** — average the log-probabilities, then softmax. Keeps the margins the probability average
  discards.
- **logit/T** — the same divided by a temperature fit by minimum NLL on held-out letters.

and wraps each in a **split conformal prediction set** at coverage 1−α: calibrate a threshold on the
non-conformity score 1−p̂(true label) over other folds, then the set for a new letter is every label whose
score is under it. The guarantee is distribution-free: with exchangeable letters, the true label is in the
set at least 1−α of the time, however badly the model is calibrated. For the desk the readouts that matter
are *how many sets are a single label* (auto-routable at that coverage) and *how many of those are wrong*.
Ten-fold cross-conformal, so every letter is scored once as a test letter; when T is fit, the calibration
fold is split so the quantile is never taken on the letters that chose T.

**Synthetic, 42 letters (top-1 35/42):**

| method | AUROC | ECE | α = 0.05: coverage · mean set · singletons (wrong) | α = 0.10 | α = 0.20 |
|---|---|---|---|---|---|
| vote | 0.64 | 0.11 | 1.00 · 5.0 · 0 (0) | 1.00 · 5.0 · 0 (0) | 0.88 · 1.05 · 40 (5) |
| logit | **0.74** | 0.12 | 0.98 · 2.2 · **18 (0)** | 0.95 · 1.7 · 24 (2) | 0.88 · 1.1 · 38 (5) |
| logit/T | 0.64 | **0.09** | 0.98 · 2.4 · 17 (1) | 0.95 · 2.1 · 21 (1) | 0.93 · 1.7 · 27 (1) |

With 38 calibration letters and six distinct vote values, the vote quantile at α ≤ 0.10 is the maximum
score and every set is all five labels — the honest answer for a coarse score on a small set, and useless.
Logit averaging alone lifts AUROC from 0.64 to 0.74 and gives 18 single-label sets at 95 % coverage with
none wrong; the naive rule from round 4 ("route if confidence ≥ 0.99") routed 28 with 2 wrong.

**Real, 300 narratives (top-1 228/300):**

| method | AUROC | ECE | α = 0.05 | α = 0.10 | α = 0.20 |
|---|---|---|---|---|---|
| vote | 0.70 | 0.15 | 1.00 · 5.0 · 0 (0) | 0.90 · 1.6 · 151 (19) | 0.80 · 1.1 · 269 (58) |
| logit | **0.76** | 0.23 | 0.95 · 2.1 · 143 (14) | 0.91 · 1.7 · 180 (24) | 0.80 · 1.1 · 273 (59) |
| logit/T | 0.72 | **0.06** | 0.95 · 2.0 · 136 (12) | 0.91 · 1.6 · 175 (22) | 0.81 · 1.1 · 259 (54) |

Fitted T: 5 on the synthetic folds, 6–8 on the real ones. Per-class coverage at α = 0.05 (logit/T) runs
near 1.0 for NOE, RFI, LOSS_MIT and PAYOFF and below it for NOT_COVERED — the guarantee is marginal, and
the class the model confuses most is the one that pays for it.

Three readings, again:

1. **The number is ordered on real text too** (AUROC 0.70–0.75), and after temperature scaling it is a
   probability in the plain sense (ECE 0.06). The vote share is not (ECE 0.14; in the round-4 run its
   0.99+ band was right 86 % of the time). `run.py`'s band table on the calibrated confidence, real set:

   | confidence band | letters | accuracy |
   |---|---|---|
   | [0.00, 0.70) | 49 | 0.51 |
   | [0.70, 0.90) | 107 | 0.70 |
   | [0.90, 0.99) | 144 | 0.90 |
   | [0.99, 1.00] | 0 | — |

   Nothing reads 0.99 any more, and when it says 0.9 it is right nine times in ten.
2. **Conformal does what it says**: 0.95 and 0.90 coverage land on 0.95 and 0.91. At 95 % coverage the desk
   can auto-route 136 of 300 letters (45 %) and 12 of them would be wrong (8.8 %); the round-4 rule on the
   vote share ("≥ 0.99") routed 169 with 24 wrong (14 %). A plain threshold on the *calibrated* number
   does about as well (≥ 0.90: 144 routed, 15 wrong) — once the score is a probability, the set and the
   threshold agree; what conformal adds is that the 95 % holds by construction, on the next 300 letters,
   without trusting the temperature fit. At 80 % coverage everything is a singleton and a fifth are
   wrong, which is just the model's error rate; the coverage knob is the queue.
3. **What it cannot do**: the wrong singletons are NOE-vs-LOSS_MIT and origination-as-NOE — the same two
   definitional gaps as the accuracy misses, now with a certificate that the model is sure. They are also
   the two boundaries the human labellers disagreed on, which is the honest reading: part of that 11 % is
   the task, not the model.
   Calibration tells the desk how much to trust the model; only definitions, a bigger model, or labeled
   examples change what it gets wrong.

**What changed in the provider:** `confidence` is now the logit-averaged, temperature-scaled top-1
(`score_temperature`, default 6.0), and the rationale reads "Scored NOE 0.71 (chosen by 100 % of option
orders) vs LOSS_MIT" so the operator sees both numbers; the vote share stays in `got.scores.*.probs`.
Exception flags are a three-way choice (yes / no / cannot tell) and are judged only for NOE (three
exceptions) and RFI (six); other case types carry none.

Not done: an independent adjudicator for the 13 (the rulings stand, but not on their own authority);
a second labeller on the other 240, which would turn "one careful pass" into a measured number there too;
conformal on
the (b)(n) category and the exception flags, which have the same logits and no labels yet on the real set;
class-conditional (Mondrian) conformal, which would buy NOT_COVERED its own coverage at the cost of set
size; a bigger local model, which is still the obvious next experiment for the origination misses.

## Round 6 — a model built for this (`jev`)

Round 5 built a calibrated decision layer out of a 4B model and some arithmetic. TypeSafe sells one: Jev,
a "System One" model that answers typed questions — `choice` returns a distribution over named options,
`noul` returns the probability a statement is true — in a single request. The obvious question is whether
the arithmetic was necessary.

`triage/jev.py` is the same split as `score.py` and imports its option descriptions, so what changes
between the two runs is the decision layer and not the prompt: the stub still extracts the three elements
and the quotes, and `case_type`, the category and the six exception flags come from one POST to
`api.typesafe.ai/v1/systemone`. All nine questions go in one request, which is the documented shape —
they are evaluated in parallel, and branching to ask the category only after the type would cost a second
round trip to learn something the first answer already gives.

### What it costs to use it

The local scorer was chosen partly because a Reg X desk can run it with no key and no egress. This provider
sends borrower correspondence to a third party. That is a data-residency decision for whoever deploys the
desk, not a default: `TRIAGE_PROVIDER` stays `stub` or `score` unless someone sets otherwise.

### Results

| | stub | **score** (Qwen3-4B, local) | **jev** (jev-1.13.0, hosted) | gemini flash-lite |
|---|---|---|---|---|
| synthetic 42 | 21 (+1 alt) | 35 (+2) | **37 (+1)** | 39 (+2) |
| — by tier plain/trap/hard | 13/4/5 | 19/6/12 | 18/7/13 | 20/7/14 |
| real 300 | 145 (48 %) | **228 (76 %)** | 197 (66 %) | not run (free tier overloaded) |
| category given type (real) | 34/101 | 106/174 | 89/120 | — |
| requests per letter | 0 | 16 local prefills | **1** | 1 |
| latency, median | 0 | 1008 ms | **338 ms** | 2–4 s |
| key required | no | no | yes | yes |
| letter text leaves the box | no | no | **yes** | yes |

Tokens, measured: 544k input and 97k output over the 300 real letters, about 1,800 in and 320 out per
letter — nine questions against one letter, billed once. No public pricing page was found at
`docs.typesafe.ai/pricing.md` or `typesafe.ai/pricing`, so the cost column is token counts rather than
money.

**It wins on text written for the task and loses on text that was not.** On the synthetic set, where every
letter was composed to be one thing, Jev beats the local scorer. On 300 real complaints it is eleven points
behind. The misses say why, and they are the mirror image of the local model's:

| direction of error | score (4B) | jev |
|---|---|---|
| called something NOT_COVERED that the labels cover | 3 | **85** |
| called something covered that the labels call NOT_COVERED | **29** | 3 |

Jev is strict where the 4B is loose. Seventy-five of Jev's misses are NOE letters it files as NOT_COVERED —
long, furious complaints that describe a servicing failure without ever naming an error. That is the same
boundary the two human labellers disagreed on (ten of their thirteen disagreements ran that way, with
Gemini taking Jev's side), and it is the boundary this set's labels were drawn by one labeller who leaned
toward coverage. **A meaningful part of the eleven-point gap is a definition, not a capability**, and the
honest next experiment is to sharpen `CASE_TYPES`' NOE/NOT_COVERED descriptions and re-run everything,
which would move all four columns.

### The calibration, which is the interesting part

| | score (4B) | jev |
|---|---|---|
| AUROC, raw | 0.64 | **0.74** |
| AUROC, best treatment | 0.72 (logit averaging) | 0.75 |
| ECE, raw | 0.15 | **0.11** |
| ECE, after temperature | 0.06 (T ≈ 6) | **0.02 (T ≈ 1.7)** |
| accuracy by confidence band | needed the fix to be monotone | 0.49 / 0.69 / 0.87 / 1.00 out of the box |

The local model needed a temperature of six to stop being overconfident. Jev needs 1.7, and its bands are
already ordered before anything is done to them: the 142 letters it scored under 0.70 are right 49 % of the
time, the 29 it scored at 0.99 are right 29 times out of 29. It does not know Reg X better than the 4B on
this set — it knows when it does not know, which is the thing the whole of round 5 was trying to
manufacture. Vote and logit rows are identical for it because there is one distribution and no option
orders to average; `flips` is 0 on all 342 letters.

What that buys at the desk, conformal at 95 % coverage:

| | routed automatically | wrong among those |
|---|---|---|
| score (4B) | 136/300 (45 %) | 12 (8.8 %) |
| jev | 58/300 (19 %) | **4 (6.9 %)** |

Two different desks. The 4B clears nearly half the mail with one mistake in eleven; Jev clears a fifth with
one in fourteen and sends the rest to a person. Which is right depends on whether the queue or the error
rate is the constraint — and that is a choice the operator can now make from numbers rather than from
vendor copy.

### The Noul criteria, and a lesson that did not generalise

The first integration asked the six exception questions as bare nouls — `instructions` only, no `criteria`.
The docs mark `criteria` optional; TypeSafe's own playground uses it, describing both outcomes. Round 5 had
already learned on the 4B that a binary judgement with only the *yes* described leans yes, so this was the
same bug twice. Adding `{true, false}` descriptions to all six, in one place shared by both providers:

| spurious flags, synthetic 42 | before | after |
|---|---|---|
| jev | 3 | **1** |
| score (4B) | 3 | **7** |

The fix worked on the model built to take criteria and backfired on the 4B, whose OVERBROAD went from two
letters to nine. A small model scoring a multiple-choice prompt degrades as the option text grows — whether
the text is a negation (round 5's first attempt) or merely long. So the descriptions live in `EXCEPTIONS`
and Jev gets them as `criteria` while `score.judge` keeps bare options, with the reason in its docstring.
This does not confound the comparison: the flag questions are independent of the case-type question, and
the accuracy and calibration numbers above are untouched by it. On the real set the criteria take Jev from
44 flagged letters to 31, and the ones that remain read correctly — 26 DUPLICATIVE on letters that say so
in as many words, 5 UNTIMELY on loans the letter says were paid off.

### What this round settles

1. **A purpose-built decision model gives you calibration for free.** Everything round 5 built by hand —
   logit averaging, temperature fitting — Jev arrives with. If the only goal were a trustworthy number, it
   would be the shorter path.
2. **It does not give you accuracy for free.** On real correspondence a local 4B with careful prompting
   beat it by eleven points, and the gap is mostly one contested definition.
3. **Conformal survives both.** It is the only layer that did not need to be re-derived for a new provider;
   `evals/conformal.py` read the hosted model's distributions unchanged, because the guarantee never
   depended on the model being good.

## Reading the results file

One row per letter: `expected` (labels), `got` (type, category, loan value, exceptions, confidence, quotes).
`results-gemini-round1.jsonl` is kept so the round-1 → round-2 regression can be diffed. `results-votes.jsonl` holds every sample of the vote run. Rows from `score`/`hybrid` carry `got.scores`: the averaged
distribution (`probs`), the rotation-mean log-probabilities (`logp`), `flips` and `label_mass` per
decision, prefill count and latency. `results-cfpb-<provider>.jsonl` are the same shape for the real set;
runs append row by row and `--resume` finishes an interrupted one.
