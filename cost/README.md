# cost/ — 100-review cost and runtime calculator

## Offline replay (default; no API key, no model calls)

```bash
.venv/bin/python cost/calculator.py
```

This reads `pilot_calls.jsonl`, `pilot_runs.json`, `rates.csv` and `assumptions.json`, then writes `usage.csv`, `report.md` and `replay.json`.
To try other rates or assumptions, edit the files or pass copies:

```bash
.venv/bin/python cost/calculator.py --rates my_rates.csv --assumptions my_assumptions.json --out /tmp/calc
```

`tests/test_scope_and_calculator.py` checks that doubling every rate doubles the API cost while measured time stays unchanged, and that changing the projected record count leaves the measured pilot results unchanged.

## Explicit pilot execution (PAID; run it only with approval)

This is the cold run: an empty cache and 1 worker.

```bash
.venv/bin/python -m pipeline run --input data/cost_100.csv --out cost/pilot/cold --cache cost/pilot/cache.sqlite --paid --budget-usd 0.50 --workers 1 --run-label pilot-cold
```

This is the warm run: a fresh run state with the same result cache. It must make 0 enrich calls.

```bash
.venv/bin/python -m pipeline run --input data/cost_100.csv --out cost/pilot/warm --cache cost/pilot/cache.sqlite --paid --budget-usd 0.50 --workers 1 --run-label pilot-warm
```

This copies the measured outputs into the submitted files.

```bash
.venv/bin/python cost/calculator.py collect
```

## Files

| File | What it is |
|---|---|
| `pilot_records.jsonl` | Cold-run result for each of the 100 pilot IDs, with the contract row hash and common labels. The warm run was identical (checked by diff). |
| `pilot_calls.jsonl` | Every attempted call in the cold and warm runs: run_id, request_id, role, model, effort, label_config, usage, latency, cost, and rate-limit headers. Failed attempts are included. |
| `pilot_runs.json` | Per-run wall-clock time, stage times, counts, cache hits, settings, and checks of the input checksum and IDs. |
| `rates.csv` | Editable prices in billing units, with a source link and the date checked. |
| `usage.csv` | Billed units × price for every charged item, mapped to `request_id`. |
| `assumptions.json` | Editable estimate inputs: budget, workers, output cap, fallback fraction, retry headroom, rate limits. |
| `report.md` | The measured 100-review table and full-run estimates. |

Local compute (laptop time and electricity) was not measured and is reported as unknown, not zero.
The provider Batch API was not used; it appears only as a hypothetical scenario.
