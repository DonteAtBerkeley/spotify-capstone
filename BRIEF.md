# BRIEF — Spotify Review Pipeline (Agentic AI Capstone)

Owner: Don. Due: Oct 21, 2026, 11:59 pm PT (extended). EMERGENCY MODE: build fast; the user's chat prompt overrides phase-by-phase stopping.
Authoritative specs (read them fully, they win over this brief if they conflict — tell Don if they do):
- `data/Final_Assignment.pdf` (or the assignment text Don provides)
- `data/GRADING_CONTRACT.md`
- `data/COST_CALCULATOR.md`
- `manifest.json` and `check_submission.py` (repo root), `data/README.md` if present

## 1. The question
Advising Spotify at the end of the review window: where should next quarter's product effort go —
access, usability, playback, or billing/support? The pipeline must make the answer inspectable.
Report the 8-topic baseline exactly as the contract defines it. Add a separate, clearly labeled
"4-option view" that maps topics into the four options and discloses where downloads/catalog/other went.

## 2. Inputs
- `data/spotify_reviews_18months.csv` — 660,622 rows, 97,400,616 bytes. Multiline text: use a real CSV parser.
  Fields: review_id, review_text, review_rating, review_likes, app_version, review_timestamp.
- Dev checkpoints: `cost_100.csv` ⊂ `checkpoint_500.csv` ⊂ `analysis_10000.csv`.
- `golden_50_to_label.csv` — Don hand-labels this. You never fill in its labels.
- The program must accept ANY input CSV path (`--input path.csv`).

## 3. Hard rules
1. Never read, print, log or commit `.env`. Load keys with dotenv. Commit only blank `.env.example`.
2. **No paid model call without Don's explicit go-ahead in chat.** Paid commands require a `--paid` flag
   and a `--budget-usd` cap. Default mode is offline/mock.
3. Before each paid run, print: input file, row count, model + effort, estimated worst-case cost, cap. Then stop.
4. Never invent results, usage, costs, timings, revenue or churn. If something is unknown, say "unknown".
5. Golden-50 human labels are never model inputs, examples, thresholds, or tuning data. Use them only to score.
6. Stars/likes/app_version are metadata. Never use them to decide topic, intent or severity.
7. Never drop a row. Every source ID ends as `completed` or `quarantined` with a reason.
8. Small modules, not one giant file. Separate: ingest, cache, enrich, validate, verify, group, rank, memo,
   export, cost calculator, dashboard. Unit tests for each.
9. Work in phases (Section 9). Stop at the end of each phase and report. Don't start the next one unasked.

## 4. Labels (copy exactly from GRADING_CONTRACT.md; summary here)
topic: access, usability, playback, downloads, catalog, billing, support, other.
- Pick the highest-severity supported problem; tie → first mentioned. Positive review → first specific
  praised feature; general praise → other. A paid-plan mention alone is not billing.
intent (precedence): cancellation → complaint → request → praise → unclear.
- Bare boycott slogans / meaningless text → unclear. "Bad app" → complaint, no specific defect invented.
severity 1–5: 1 none/praise/request/unclear; 2 dislike/generic/cosmetic; 3 degraded, workaround remains;
4 core task blocked; 5 explicit serious financial/privacy/data harm. Anger, crashes, price, or
cancellation alone do not raise severity. Missing context → needs_review=true.
sentiment: −1 to 1. evidence_quote: exact substring of review_text (checked in code).
entities: only things literally in the text. label_config: "model+prompt+schema-version".
Keep a `labels/EXAMPLES.md` with ~15 worked examples from DEV files only (not golden), showing how the
definitions were applied. The assignment requires these examples.

## 5. Pipeline stages (code vs model)
| # | Stage | Owner | Input → Output | Stop/failure rule |
|---|---|---|---|---|
| 1 | Prepare | code | CSV → SQLite + ingestion report, row SHA-256 (contract's `row_sha`), exact-text groups, pending queue | No model calls. Empty text → quarantined `empty_review_text` |
| 2 | Enrich | model + code validation | ≤50 distinct texts per request → validated records | Validate every returned ID, schema, ranges, quote. Invalid → retry once with the error → else quarantine with reason + attempts. Save atomically after each batch |
| 3 | Verify | separate model call + code | declared random sample (fixed seed), original text only, NOT the first label → disagreement report | Code compares; Don inspects disagreements |
| 4 | Group | code (+ small model for issue names on bounded examples) | complaint/cancellation records → stable issue IDs + membership.csv | Saved mapping; ranking never needs a model |
| 5 | Rank | code | membership + records → ranking.csv | Exact contract formula; tie → ascending issue_id; 6-decimal half-up means |
| 6 | Recommend | model + code check | ranking + bounded evidence pack ONLY → memo + claims.csv | Code rejects any cited ID/number not in saved outputs |

Cache: key = exact text + model + effort + prompt version + schema version. Duplicates get
`cache_source_id` pointing directly at a completed original with model-call evidence. Every original ID
stays its own row and counts in aggregates. Reused results are not logged as new calls.

## 6. Models and cost controls
- Default enricher: GPT-6 Luna with `reasoning.effort` set explicitly to `"none"` (default is medium, which costs more).
  Also build a Jev (TypeSafe Choice) adapter so we can compare on dev data. Pick by measured quality/cost/time.
- Stronger-model fallback: off by default; if enabled, capped fraction (e.g. ≤2%) and capped dollars.
- Output-token cap per request; compact JSON output.
- **Total project API budget: $20.** Targets: dev runs ~$2, full enrichment ~$14, verify/group/memo ~$1.50, reserve ~$2.50.
- One shared spend ledger: reserve worst-case cost before each call; stop admitting work when
  spent + reserved + next reservation > cap. Save progress and exit cleanly.
- Start with 1 worker; try 2 only after measurement. Bounded retries with backoff + jitter for 429/5xx/timeouts.
  Timeouts = "unknown charge", flag for reconciliation.
- Consider the provider Batch API for the full run if eligible; it goes in estimates until actually used.

## 7. Tests (must exist and show real outcomes)
- Unit tests with a mock model: malformed JSON, missing ID, foreign ID, duplicate ID, bad quote, out-of-range values.
- Injection test: synthetic review telling the model to ignore instructions / label as praise. Marked synthetic, excluded from aggregates.
- Planted-error test: deliberately wrong label in a separate test copy; the verifier/code must catch it.
- Interruption/resume: kill mid-run, rerun, show zero re-enrichment of completed IDs; save
  `checkpoint_before.json` / `checkpoint_after.json`. Don records the screen.
- Golden eval: per-field agreement, severity exact + MAE, confusion table, ambiguous count, every disagreement saved.

## 8. Required outputs
`grading/` (run.json, ingestion.json, records.jsonl.gz, membership.csv, ranking.csv, claims.csv, calls.jsonl,
checkpoint_before.json, checkpoint_after.json) — exact formats in GRADING_CONTRACT.md.
`cost/` (calculator, README with offline replay + separate explicit pilot command, pilot_records.jsonl,
pilot_calls.jsonl, rates.csv with dated source links, usage.csv, report.md) — per COST_CALCULATOR.md.
Offline replay needs no API key. Doubling rates must double API cost and leave time unchanged.
`evals/`, `memo.md`, run_log.jsonl, run_summary.json, README.md with rubric→evidence map,
architecture diagram, one real review traced end to end, one failed/ambiguous case, limitations,
and an AI-use disclosure.

## 9. Phases (stop after each)
- P1 Setup + ingest (free). Run `check_submission.py profile` and `reference`. Confirm 660,622 / 13 empty /
  159,701 missing app_version / 484,189 distinct nonempty texts / no repeated IDs.
- P2 Labels, prompts v1, EXAMPLES.md, golden labeling sheet for Don (blank labels).
- P3 Enricher + validator + cache + ledger + resume, all against a MOCK model. All tests pass. $0.
- P4 Paid: 100-review cold run then warm run (cap $0.50). Build the calculator + report. → Don decides.
- P5 Paid: 500 run + interrupt/resume recording. (Class 7 demo.)
- P6 Paid: 10,000 run; refresh full-run estimate. → Don gives go/no-go for the full run under $20.
- P7 Full run (Don launches it from Terminal).
- P8 Verify, golden eval, group, rank, memo, claims, grading export, run the checker.
- P9 Database + backend + deployed dashboard (read-only; shows metrics, ranking, saved AI recommendation
  with issue/review evidence; no paid calls from visitors; no keys in frontend).
- P10 README, disclosure, clean-environment test, signed-out link check.

## 10. Dashboard (P9 preferences)
Don knows Next.js/React. A simple option: one Next.js app (pages + API routes as the backend) with a hosted
Postgres database. Check current free-tier limits; if 660k enriched rows don't fit, propose an alternative.
The backend must read from the database; displayed numbers must match ranking.csv/claims.csv.
