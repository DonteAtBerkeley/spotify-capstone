# Spotify Review Pipeline — Agentic AI Capstone (Donte Gomes)

> **Status at submission (Oct 21, 2026, ~midnight PT): the full-corpus enrichment run was still in progress.**
> This repo is submitted as-is at the deadline. Everything below separates what was measured from what is still pending.
> No result, cost, or count in this README is estimated unless it is labeled as an estimate.

## Question
Advising Spotify at the end of the May 2022 – Nov 2023 review window: where should the next quarter of product
effort go — access, usability, playback, or billing/support?

## What is in this repo
| Path | What it is |
|---|---|
| `pipeline/` | The staged program (one small module per stage): ingest → enrich → verify → group → rank → memo |
| `tests/` | Unit tests run against a mock model (malformed output, foreign/missing IDs, bad quotes, injection, resume) |
| `cost/` | 100-review cost/runtime calculator, pilot outputs, rates and usage (see `cost/README.md` for offline replay) |
| `grading/` | Grading export folder per `GRADING_CONTRACT.md` (`ingestion.json` is complete; other files pending the full run) |
| `prompts/`, `labels/` | Prompt versions and label definitions |
| `tools/` | Golden-50 labeling helper (shows one review at a time; suggests no answers) |
| `check_submission.py`, `manifest.json` | Course-provided checker and dataset manifest |

## Measured so far
- **Ingestion profile** (`grading/ingestion.json`, produced by the course helper): 660,622 rows, 13 empty texts,
  159,701 missing app versions, 0 duplicate review IDs, file SHA-256 `1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6`.
- **Full-run preflight** (from the run's own log, run ID `full-20261020T233634-2a9b43`):
  model `gpt-6-luna`, reasoning effort `none`, label config `gpt-6-luna:effort=none+enrich-p1+s1`,
  batch size 50, 16 workers, budget cap $15.00, 483,710 distinct texts left to send at start
  (66,077 exact-text cache hits reused from earlier runs).
- The run's preflight worst-case enrichment estimate was $23.98, above the $15.00 cap, so the run is designed to
  **stop cleanly at the cap and save progress**; it is resumable with the same command.

## Pending at the deadline
- Completion of full-corpus enrichment; final completed/quarantined counts
- Verification sample, golden-50 evaluation, grouping, ranking, memo and `claims.csv`
- Full `grading/` export and checker result (`self-check.json`)
- Database + backend + deployed dashboard (live URL)

Final numbers will be taken only from saved run logs. If the repo is updated after the deadline, the commit history shows exactly what changed and when.

## How to run
```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your own key; never commit .env
# Offline cost replay (no API key, no paid calls): see cost/README.md
# Paid run (explicit flag required):
.venv/bin/python -m pipeline run --input data/spotify_reviews_18months.csv --out runs/main --paid --budget-usd 15 --workers 16 --run-label full
```
Dataset: BwandoWando, *3.4 Million Spotify Google Store Reviews* (v2, Kaggle, CC0), course 18-month extract — not committed; see `manifest.json` for checksums.

## Known limitations / disclosures
- Jev (TypeSafe) was not evaluated; GPT-6 Luna was used for enrichment without a measured comparison.
- Worker count went to 16 without a measured 2-worker comparison; the throughput scaling was an assumption.
- Reviews are self-selected, historical app-store evidence, not a representative sample of Spotify users.

## AI-use disclosure
_(To be written by Donte in his own words: which AI tools wrote code — e.g. Claude Code — which models labeled data, and which parts he did himself, such as the golden-50 human labels.)_
