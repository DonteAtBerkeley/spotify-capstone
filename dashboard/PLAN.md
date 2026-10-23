# Dashboard plan (P9): hosted Postgres + backend + read-only frontend

Status: **plan only.** Nothing has been built, deployed or connected yet.

## Goals and hard rules
- Visitors only read saved results. There are **no model calls** anywhere in the deployed app: no LLM SDK is installed and no model key exists in Vercel.
- **No keys in the frontend.** The only secret is a *read-only* Postgres URL, kept as a server-side environment variable (never `NEXT_PUBLIC_*`) and used only in server code.
- Every number shown must match `grading/ranking.csv` and `grading/claims.csv` exactly. A check script enforces this (see "Consistency check").

## Architecture
```
grading/ + runs/main outputs ──(Don runs locally: scripts/load_db.py, ADMIN url from .env)──▶ Neon Postgres (free)
                                                                                            │  read-only role
Browser ──▶ Vercel (Next.js App Router) ── server components / route handlers ── SELECT ────┘
            (no keys in client bundle; responses cached with revalidate)
```
- **Database: Neon free plan.** Checked 2026-10-23 at neon.com/pricing: 1 GB storage per project, 100 CU-hours per project, 5 GB public egress per project, scale-to-zero after 5 minutes, no credit card.
- **Backend and frontend: one Next.js app on Vercel Hobby.** Checked 2026-10-23 at vercel.com/docs/plans/hobby: free, non-commercial personal use only (a class project fits), 1,000,000 function invocations and 100 GB fast data transfer per month, 300 s maximum function duration.
- **The backend reads the database on request** through route handlers (`/api/metrics`, `/api/ranking`, `/api/issues/[id]`, `/api/reviews/[id]`, `/api/memo`). Pages call the same query functions server-side.
- **Caching:** responses use `revalidate`. The data is static after the run, so most visitors are served from cache and seldom wake the scale-to-zero database.

## Will 660k enriched rows fit in 1 GB? (estimate, not measured)
- **Measured from the run-2 snapshot:** an average evidence quote is 20.5 bytes and average entities JSON is 8.2 bytes. The source CSV is 97.4 MB in total.
- **Estimate:**
  - `records`, typed columns without review text: about 150 bytes per row × 660,622 ≈ 100 MB, plus about 40 MB of primary-key index.
  - `reviews` with full text: about 100 to 130 MB.
  - Total: roughly **300 to 400 MB**, under the 1 GB limit.
- **Measure it after loading** with `pg_total_relation_size`. If it doesn't fit, the fallback is to drop `review_text` for non-complaint rows and keep text only for complaint/cancellation reviews and cited evidence.

## Schema
| table | columns | notes |
|---|---|---|
| `reviews` | review_id PK, review_text, review_rating, review_likes, app_version, review_timestamp, month | source fields unchanged |
| `records` | review_id PK→reviews, status, reason, topic, intent, severity, sentiment, evidence_quote, entities text[], needs_review, cache_source_id, label_config | straight from `records.jsonl.gz` |
| `issues` | issue_id PK, name, method | from `issues.json` |
| `membership` | issue_id, review_id, PK(issue_id, review_id) | from `membership.csv` |
| `ranking` | rank, issue_id, complaint_count, severity_sum, mean_severity TEXT, priority_score | stored **as exported strings**, so the 6-decimal half-up means are never re-rounded |
| `claims` | claim_id PK, issue_id, metric, value TEXT | from `claims.csv` |
| `memo` | id, body_md, label_config, created_at | the saved AI recommendation (`memo.md`) |
| `run_meta` | key, value jsonb | run.json, coverage counts, cost summary, golden-eval summary |

- **Indexes:** `records(intent, topic)`, `records(month)`, `membership(issue_id)`.
- **Roles:**
  - `loader` owns the tables and is used only from Don's machine.
  - `dashboard_ro` has `CONNECT` and `USAGE` plus `SELECT` on these tables, and nothing else.

## Pages
1. **Overview**
   - Coverage: 660,622 rows, completed and quarantined counts by reason.
   - Topic and intent distribution, reviews per month, and the share flagged `needs_review`.
   - Every number comes from `run_meta` and `records`.
2. **Ranking**
   - The baseline table, matching `ranking.csv` row for row.
   - A separately labelled "4-option view" (access / usability / playback / billing+support) that discloses where downloads, catalog and other went (BRIEF §1).
3. **Issue detail**
   - Name, the metrics from `ranking`, and paginated member reviews (50 per page).
   - Each review shows its quote highlighted inside the full text, plus stars and date, labelled as metadata.
4. **Recommendation**
   - The saved memo. Claim tags like `[C1]` link to the claims table and the issue page.
   - It says plainly that the memo is model-written prose and that code fills in the numbers.
5. **Method and quality**
   - The pipeline diagram, label definitions, golden-50 agreement (from `evals/golden_report.json`), verification disagreements, the cost summary, and limitations.

## Consistency check (part of the deploy checklist)
`scripts/check_dashboard.py <deployed-url>` fetches `/api/ranking` and `/api/memo` claims. It diffs them against `grading/ranking.csv` and `grading/claims.csv` and exits non-zero on any mismatch. Run it after every load and deploy.

## Security checklist
- [ ] The client bundle contains no environment values: run `grep` on `.next/static` for the DB host.
- [ ] Only `dashboard_ro` credentials are in Vercel. The loader URL exists only in Don's local `.env`.
- [ ] Every query is parameterized and has a page-size cap. There are no writes and no raw SQL from query strings.
- [ ] No OpenAI, Anthropic or TypeSafe key is set in Vercel. No model SDK is in `package.json`.
- [ ] The production URL opens in a signed-out or private window.

## Account steps Don must do himself
1. **Neon:** sign up (free, no card).
   - Create a project named `spotify-capstone`, in the region closest to Vercel's default (US East).
   - Copy the **owner** connection string into the local `.env` as `DATABASE_URL_ADMIN`. Never paste it into chat.
2. **Neon:** in the SQL editor, run the read-only role SQL that I'll put in `dashboard/sql/roles.sql`.
   - Choose the `dashboard_ro` password yourself.
   - Save the pooled read-only URL locally as `DATABASE_URL_RO`.
3. **Load the data:** run `scripts/load_db.py`. It reads `DATABASE_URL_ADMIN` from `.env` and loads data only after the final export passes `check_submission.py`.
4. **GitHub:** create the repository (private is fine for Vercel Hobby).
   - Push the code, or ask me to commit and push once the repository exists.
   - Make sure `.env`, `*.sqlite`, `data/*.csv` and `runs/` stay ignored.
5. **Vercel:** sign up for Hobby (GitHub login) and import the repository.
   - Set **Root Directory** to `dashboard/`.
   - Add the environment variable `DATABASE_URL` = the **read-only** pooled URL, for Production only, then deploy.
6. **Public access:** confirm the production deployment isn't behind Vercel Authentication, so the instructor can open it signed out.
7. **Spend safety:** both free plans pause when they hit limits instead of charging, so leave billing details off both accounts.

## Build order (after you approve)
1. `dashboard/sql/schema.sql` and `roles.sql`.
2. `scripts/load_db.py`, tested against a local Postgres or a Neon branch with the 500-row checkpoint data.
3. The Next.js app: API routes first, then pages.
4. `scripts/check_dashboard.py`.
5. Deploy, then run the consistency check and the signed-out check.
