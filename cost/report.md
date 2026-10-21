# 100-review pilot: measured cost/runtime + full-run estimate

Generated offline by `python cost/calculator.py` from `pilot_calls.jsonl`, `pilot_runs.json`, `rates.csv`, `assumptions.json`. No API calls. Formula per call: `item_cost = billed_units x price_per_unit`, `total = sum(item_cost)`; uncached input = input_tokens - cached_tokens.

## Measured on the pilot (cost_100.csv)

- Input: `data/cost_100.csv` sha256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` (matches manifest.json: True); 100 IDs match cost_100.csv: True
- Settings: {"model": "gpt-6-luna", "effort": "none", "label_config": "gpt-6-luna:effort=none+enrich-p1+s1", "batch_size": 50, "workers": 1, "budget_cap_usd": 0.5}
- Rate-limit headers seen: {"rpm": 5000, "tpm": 2000000}

| | Cold run | Warm run |
|---|---|---|
| run_id | `pilot-cold-20261020T232057-fd668c` | `pilot-warm-20261020T232258-0564ff` |
| rows / completed / quarantined | 100 / 100 / 0 | 100 / 100 / 0 |
| unique texts / result-cache hits | 100 / 0 | 100 / 100 |
| enrich: requests (failed) | 3 (0) | 0 (0) |
| enrich: in / out / cached tokens | 5086 / 4112 / 0 | 0 / 0 / 0 |
| enrich: API cost USD | 0.002565 | 0.000000 |
| verify: requests (failed) | 1 (0) | 0 (0) |
| verify: in / out / cached tokens | 883 / 393 / 0 | 0 / 0 / 0 |
| verify: API cost USD | 0.000285 | 0.000000 |
| group: requests (failed) | 1 (0) | 0 (0) |
| group: in / out / cached tokens | 358 / 119 / 0 | 0 / 0 / 0 |
| group: API cost USD | 0.000095 | 0.000000 |
| memo: requests (failed) | 1 (0) | 0 (0) |
| memo: in / out / cached tokens | 1106 / 264 / 0 | 0 / 0 / 0 |
| memo: API cost USD | 0.000243 | 0.000000 |
| **total API cost USD** | **0.003187** | **0** |
| calls with unknown charge (timeouts) | 0 | 0 |
| wall-clock s (end to end) | 42.57 | 0.02 |
| stage s | enrich 31.22, verify 4.35, group 2.60, rank 0.00, memo 4.38 | enrich 0.00, verify 0.00, group 0.00, rank 0.00, memo 0.00 |
| cost per 1,000 input rows USD | 0.031873 | 0.000000 |
| cost per completed record USD | 0.000032 | 0.000000 |
| enrich throughput (reviews/min, 1 worker) | 192.2 | n/a (0 sent) |

Local compute: unknown (not measured); no API charge. Shown separately from API spend.

## Full-run estimate (spotify_reviews_18months.csv)

- Rows accounted: 660,622 = 660,609 nonempty outputs + 13 empty-text quarantines
- Texts to enrich: 484,189 (exact-text reuse ON)
- Measured enrich cost per distinct text (incl. pilot retries): $0.00002565
- Verify sample 50 x $0.00002848; group+memo fixed overhead $0.000338 (added once, not per review)
- Fallback: max fraction 0.0 (model: None)
- Output-token cap: 80/review (+64 per request)

| Scenario | API cost USD |
|---|---|
| Base (reuse ON, measured mix) | 12.42 |
| Conservative (enrich x1.25, verify/group/memo x2) | 15.53 |
| No-reuse comparison (660,609 texts) | 16.94 |
| Batch API scenario, enrich only (NOT used; hypothetical) | 6.21 |
| Budget | 15.00 |

> **WARNING: conservative scenario exceeds the $15.00 budget.** The run's spend ledger stops admitting batches at the cap; progress is saved and resumable.

### Time (MODELED: only 1 worker was measured)

- Measured per worker: 192.2 reviews/min, 5.77 requests/min
- Rate-limit ceiling: tokens counted per request ~5759 (input + max_output_tokens) -> max workers by TPM 60, by RPM 867
- Chosen workers: 16 (effective 16) -> modeled 3075 distinct reviews/min (linear scaling assumed)
- Enrichment: 2.62 h; ingest 28.9 s; downstream (measured once) 11.3 s; total 2.64 h
- Parallelism shortens elapsed time; it does not lower cost per classification. Rate limits, retries and provider latency can make real throughput lower than modeled.

## Controls demonstrated

- Shared spend ledger reserves worst-case cost before each call; admission stops at cap (tests/test_enrich.py::test_budget_cap_stops_admission).
- Bounded retries with backoff+jitter; timeouts flagged `unknown_charge` (test_transport_*, test_timeout_flags_unknown_charge).
- Atomic per-batch save; interrupt/resume with zero re-enrichment (test_interrupt_and_resume_no_reenrichment, test_end_to_end).
- Exact-text result cache: warm run made 0 enrich calls (table above).
