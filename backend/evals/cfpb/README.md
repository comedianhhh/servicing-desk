# The real letter set

300 consumer narratives from the **CFPB Consumer Complaint Database**, product = Mortgage, received
2015–2024.

## Where they come from

The CFPB publishes complaints it receives; where the consumer consents, the narrative is published with
personal details scrubbed by the Bureau (`XXXX` for names, dates and places, `{$2000.00}` for amounts).
The Bureau stopped publishing narratives in 2025 and the current bulk export
(`files.consumerfinance.gov/ccdb/complaints.csv.zip`) no longer carries the column at all, so this set is
drawn from a mirror of the older export on the Hugging Face Hub:
`BEE-spoke-data/consumer-finance-complaints`.

**Status:** works of the US federal government, public domain (17 U.S.C. § 105), published by the Bureau
for reuse. Nothing here was scraped, deanonymised, or joined against another source, and nothing was added
to what the Bureau published. The files in this directory are a subset of that public data plus labels
written for this project.

Reproduce the selection:

```
python -m evals.cfpb sample --parquet <shard-0.parquet> --n 300 --seed 0
```

(one 126 MB shard of the mirror; 672k complaints, 10,120 of them mortgage complaints with a narrative,
filtered to 300–2,500 characters and sampled proportionally — not stratified.)

## What is in here

| file | what it is |
|---|---|
| `letters.jsonl` | the 300 narratives with their CFPB metadata (issue, sub-issue, company, date) |
| `labels-second.jsonl` | labeller 1: all 300, one line of reasoning each |
| `labels-gemini.jsonl` | labeller 2 (the Gemini provider, blind): the random 60 of `agreement-sample.txt` |
| `agreement-sample.txt` | the random 60 ids, `python -m evals.cfpb agreement` (seed 1) |
| `adjudicated.jsonl` | the 13 the labellers disagreed on, ruled with the rule cited |
| `labels.jsonl` | the merge the evals read — built, not edited by hand |

## Reading them

These are complaints *about* a servicer written to a regulator, not letters *to* a servicer. They are
angrier, longer and less specific than the correspondence a Reg X desk actually receives, and a good
fraction concern origination rather than servicing. That gap is the point: `letters.py` measures the traps
the project thought of, this set measures prose nobody on the project wrote.

They are also real people's bad months. Use them to measure a classifier; do not quote them as anecdotes.
