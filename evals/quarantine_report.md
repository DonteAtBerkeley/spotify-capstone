# Quarantined reviews after full runs 1 and 2

**Source:** `runs/main/records.jsonl` and `runs/main/calls.jsonl`, the snapshots written when run 2 ended (2026-10-22 11:56). The live database wasn't queried while run 3 was writing.

## Counts
| Reason | Reviews | What happened |
|---|---|---|
| `validation_failed:quote_not_in_text` | 319 | The model's evidence quote wasn't an exact substring of the review, either at first or after one targeted retry that told it so. |
| `validation_failed:malformed_response` | 151 | **All 151 were truncated by my own output-token cap** (`incomplete:max_output_tokens`). The batch of 50 hit its 4,064-token cap; the retry in halves of 25 hit its 2,064 cap too. |
| `same_text_as_quarantined:<id>` | 9 | Exact duplicates of a quarantined review. They follow their original and were never sent separately. |
| **Total quarantined by the enricher** | **479** | Run 1: 187. Run 2: 292. |
| `empty_review_text` | 13 | Contract-required quarantines at ingest. These are not failures. |
| `unprocessed_pending` | 72,716 | Not a quarantine: these were still pending when run 2 stopped, and run 3 is processing them now. |

## Were any quarantined for transport or timeout reasons?
**No.** By design, a batch whose transport retries run out stays **pending**, never quarantined.

- **Runs 1 and 2 both stopped on network failures:**
  - Run 1: `ConnectionError`, 17 batches left pending.
  - Run 2: `ReadTimeout`, 9 batches left pending.
  - Those batches went back into the queue, which is part of why run 3 exists.
- **Failed enrich attempts in the call log:**
  - Transport: 289 `ReadTimeout`, 223 `ConnectionError`, 5 `ChunkedEncodingError` and 2 HTTP 520 (CDN error).
  - Validation: 201 quote failures and 47 truncations, recorded at batch level.
  - Malformed JSON: 4.
- **517 attempts are flagged `unknown_charge=1`** (timeouts and network drops). Their real charge is unknown.
  - They are logged with 0 tokens and $0, so the $10.70 "already spent" figure *excludes* any charge for them.
  - During each run, the ledger booked the full reservation for each one, but that booking isn't persisted.
  - **Reconcile the total against the OpenAI usage dashboard.**

## The truncated 151 are config failures, so requeue them
The cap was 80 output tokens per review. Long reviews (and their quotes) overflowed it. That's my limit, not a model labeling failure. The prompt, schema and model are unchanged, so `label_config` stays the same and any result counts the same as the rest.

Requeuing the 319 quote failures is optional. They are real model-output failures, and the contract allows them to stay quarantined. Smaller batches often fix them, and the cost is similar.

**Steps.** Run these only **after run 3 has fully finished**, since they write to the same state:

1. Dry run, which changes nothing and prints the count:
   ```bash
   .venv/bin/python -m pipeline requeue --run-dir runs/main --reason validation_failed:malformed_response --reason validation_failed:quote_not_in_text
   ```
2. Apply. Each row is copied to `quarantine_history` before becoming pending, so nothing is lost:
   ```bash
   .venv/bin/python -m pipeline requeue --run-dir runs/main --reason validation_failed:malformed_response --reason validation_failed:quote_not_in_text --apply
   ```
3. **Paid. Needs Don's "go".** Re-enrich only the pending reviews, using batches of 10 and twice the output cap, under a separate label and cap:
   ```bash
   .venv/bin/python -m pipeline run --input data/spotify_reviews_18months.csv --out runs/main --paid --budget-usd 0.25 --workers 2 --batch-size 10 --out-tokens-per-review 160 --run-label requeue
   ```
   - Rough estimate: **about $0.03**, assuming roughly 48 requests and about 100 output tokens per long review. This is not measured.
   - The run also redoes verify, group, rank and memo on the final data. Those costs are measured at a few tenths of a cent each.

None of these steps affects the checkpoint evidence. Requeued IDs were never in `checkpoint_before.json`, and resume-phase calls never re-send completed IDs.
