"""Command line. Default is OFFLINE (mock model). Paid calls require --paid AND --budget-usd.

  python -m pipeline run --input data/cost_100.csv --out runs/x                 # mock, $0
  python -m pipeline run --input data/cost_100.csv --out runs/x --paid --budget-usd 0.50
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from .config import ModelConfig
from .enrich import Enricher, cache_key
from .export import iter_calls, iter_records, write_checkpoint, write_jsonl
from .ingest import file_sha256, ingest
from .ledger import BudgetExceeded, Ledger
from .llm import MockClient, OpenAIClient
from .prompts import ENRICH_INSTRUCTIONS, enrich_payload
from .config import call_cost
from .store import Store

ALL_STAGES = ("enrich", "verify", "group", "rank", "memo")


def worst_case(store, cfg, rates_model):
    pending = [p for p in store.pending() if p[1].strip()]
    seen, reps = set(), []
    for rid, text in pending:
        k = cache_key(text, cfg)
        if k not in seen and not store.cache_get(k):
            seen.add(k); reps.append(text)
    total = 0.0
    for i in range(0, len(reps), cfg.max_batch):
        b = reps[i:i + cfg.max_batch]
        est_in = int((len(ENRICH_INSTRUCTIONS) + len(enrich_payload(b))) / 2.0) + 50
        total += call_cost(rates_model, est_in, cfg.output_cap(len(b)))
    return len(pending), len(reps), total


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest + stages on any CSV")
    r.add_argument("--input", required=True)
    r.add_argument("--out", required=True, help="output dir (state.sqlite, exports)")
    r.add_argument("--state", help="state DB (default OUT/state.sqlite)")
    r.add_argument("--cache", help="result-cache DB (default OUT/cache.sqlite)")
    r.add_argument("--stages", default=",".join(ALL_STAGES))
    r.add_argument("--paid", action="store_true", help="use the real API (else mock)")
    r.add_argument("--budget-usd", type=float, help="hard spend cap for THIS invocation (required with --paid)")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--rpm", type=float, help="shared request-per-minute ceiling")
    r.add_argument("--model", default="gpt-6-luna")
    r.add_argument("--effort", default="none")
    r.add_argument("--batch-size", type=int, default=50)
    r.add_argument("--stop-after-batches", type=int, help="testing/demo: stop admitting after N batches")
    r.add_argument("--checkpoint-before", help="write completed_ids here if enrichment is interrupted")
    r.add_argument("--checkpoint-after", help="write completed_ids here when a resumed enrichment finishes")
    r.add_argument("--dry-run", action="store_true", help="print the preflight and stop")
    r.add_argument("--run-label", default="run")
    r.add_argument("--out-tokens-per-review", type=int, default=80, help="output-token cap per review in a request")
    q = sub.add_parser("requeue", help="move quarantined records back to pending (history kept; no API calls)")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--reason", action="append", required=True, help="reason prefix; repeatable")
    q.add_argument("--apply", action="store_true", help="without this flag: dry run, just list counts")
    g = sub.add_parser("export-grading", help="assemble grading/ from a finished run (no API calls)")
    g.add_argument("--input", required=True, help="the CSV the run classified")
    g.add_argument("--run-dir", required=True, help="run --out dir (state.sqlite, ranking.csv, ...)")
    g.add_argument("--out", default="grading")
    a = ap.parse_args(argv)

    if a.cmd == "requeue":
        from .requeue import requeue
        rd = Path(a.run_dir)
        store = Store(rd / "state.sqlite", rd / "cache.sqlite")
        ids = requeue(store, a.reason, note="cli requeue " + ",".join(a.reason), dry_run=not a.apply)
        print(f"[requeue] {'moved to pending' if a.apply else 'DRY RUN, would requeue'}: {len(ids)} records "
              f"(reasons {a.reason}); history kept in quarantine_history")
        return 0

    if a.cmd == "export-grading":
        from .grading import export_grading
        rd = Path(a.run_dir)
        if not (rd / "state.sqlite").exists():
            ap.error(f"no state.sqlite in {rd}")
        summary = export_grading(Store(rd / "state.sqlite", rd / "cache.sqlite"), a.input, rd, a.out)
        return 1 if summary["missing_files"] or summary["records"] != summary["expected"] else 0

    if a.paid and a.budget_usd is None:
        ap.error("--paid requires --budget-usd")
    if a.batch_size > 50 or a.batch_size < 1:
        ap.error("--batch-size must be 1..50 (contract)")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    store = Store(a.state or out / "state.sqlite", a.cache or out / "cache.sqlite")
    # Mock runs are labeled as mock so their records/calls can never pass as paid evidence.
    # The output cap is not part of label_config: it limits length, not the prompt/schema/labels.
    cfg = ModelConfig(model=a.model if a.paid else "mock-model", effort=a.effort, max_batch=a.batch_size,
                      out_tokens_per_review=a.out_tokens_per_review)
    run_id = f"{a.run_label}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    stages = [s for s in a.stages.split(",") if s]
    log_path = out / "run_log.jsonl"

    def log(msg):
        print(msg, flush=True)
        with open(log_path, "a") as f:
            f.write(json.dumps({"t": time.time(), "run_id": run_id, "msg": msg}) + "\n")

    t_start = time.monotonic()
    n = ingest(store, a.input, run_id=run_id)
    t_ingest = time.monotonic() - t_start
    pending, distinct, wc = worst_case(store, cfg, cfg.model if a.paid else "gpt-6-luna")
    pre = {"run_id": run_id, "input": a.input, "input_sha256": file_sha256(a.input), "rows_in_file": n,
           "rows_in_state": store.review_count(), "rows_in_scope": store.q("SELECT COUNT(*) FROM temp.scope")[0][0], "pending_nonempty": pending, "distinct_texts_to_send": distinct,
           "mode": "PAID" if a.paid else "MOCK (no API calls)", "model": cfg.model, "effort": cfg.effort,
           "label_config": cfg.label_config, "batch_size": cfg.max_batch, "workers": a.workers,
           "est_worst_case_enrich_usd": round(wc, 4), "budget_cap_usd": a.budget_usd, "stages": stages}
    log("[preflight] " + json.dumps(pre))
    if a.dry_run:
        return 0

    client = OpenAIClient(cfg.model, cfg.effort, cfg.timeout_s) if a.paid else MockClient()
    # The cap is cumulative across reruns with the same --run-label in this state (resume can't reset it).
    prior = store.q("SELECT COALESCE(SUM(cost_usd),0) FROM calls WHERE run_id LIKE ?", (f"{a.run_label}-%",))[0][0]
    ledger = Ledger(a.budget_usd if a.budget_usd is not None else float("inf"), already_spent=prior)
    log(f"[budget] cap ${a.budget_usd} for label '{a.run_label}'; already spent by earlier runs with this label: ${prior:.6f}")
    store.start_run(run_id, " ".join(sys.argv), a.input)
    summary = {"preflight": pre, "ingest_s": round(t_ingest, 3), "stage_s": {}}
    try:
        if "enrich" in stages:
            t = time.monotonic()
            en = Enricher(store, client, cfg, ledger, run_id, workers=a.workers, rpm=a.rpm, log=log,
                          stop_after_batches=a.stop_after_batches, rates_model="gpt-6-luna")
            summary["enrich"] = en.run()
            summary["stage_s"]["enrich"] = round(time.monotonic() - t, 3)
            if en.stop_reason and a.checkpoint_before:
                k = write_checkpoint(store, a.checkpoint_before)
                log(f"[checkpoint] before: {k} completed_ids -> {a.checkpoint_before}")
            if not en.stop_reason and en.phase == "resume" and a.checkpoint_after:
                k = write_checkpoint(store, a.checkpoint_after)
                log(f"[checkpoint] after: {k} completed_ids -> {a.checkpoint_after}")
        remaining = len([p for p in store.pending() if p[1].strip()])
        summary["pending_after_enrich"] = remaining
        records = list(iter_records(store))
        downstream = [s for s in stages if s != "enrich"]
        if downstream and remaining:
            log(f"[run] {remaining} reviews still pending; skipping downstream stages until enrichment finishes")
            downstream = []
        texts = dict(store.q("SELECT review_id, review_text FROM reviews JOIN temp.scope USING(review_id)"))
        if "verify" in downstream:
            from .verify import run_verify
            t = time.monotonic()
            summary["verify"], dis = run_verify(store, client, ledger, run_id, records, texts, out, "gpt-6-luna", log=log)
            summary["stage_s"]["verify"] = round(time.monotonic() - t, 3)
        names, pairs = {}, None
        if "group" in downstream or "rank" in downstream or "memo" in downstream:
            from .group import membership, run_group
            t = time.monotonic()
            if "group" in downstream:
                pairs, names, _ = run_group(store, client, ledger, run_id, records, out, "gpt-6-luna", log=log)
            else:
                pairs = membership(records)
            summary["stage_s"]["group"] = round(time.monotonic() - t, 3)
        ranking = None
        if "rank" in downstream or "memo" in downstream:
            from .rank import rank, write_ranking
            t = time.monotonic()
            sev = {r["review_id"]: r["severity"] for r in records if r["status"] == "completed"}
            ranking = rank(pairs, sev)
            write_ranking(ranking, out / "ranking.csv")
            summary["stage_s"]["rank"] = round(time.monotonic() - t, 3)
            log(f"[rank] issues={len(ranking)}")
        if "memo" in downstream:
            from .memo import run_memo
            t = time.monotonic()
            run_memo(store, client, ledger, run_id, ranking, names, records, out, "gpt-6-luna", log=log)
            summary["stage_s"]["memo"] = round(time.monotonic() - t, 3)
    except BudgetExceeded as e:
        log(f"[run] budget cap reached: {e}. Progress is saved; rerun to resume.")
        summary["stopped"] = f"budget: {e}"
    finally:
        wall = time.monotonic() - t_start
        summary["wall_s"] = round(wall, 3)
        summary["ledger"] = ledger.snapshot()
        summary["run_spent_usd_from_calls"] = round(store.spent(run_id), 8)
        summary["run_calls_by_role"] = dict(store.q("SELECT role, COUNT(*) FROM calls WHERE run_id=? GROUP BY role", (run_id,)))
        store.end_run(run_id, wall, summary)
        write_jsonl(out / "records.jsonl", iter_records(store))
        write_jsonl(out / "calls.jsonl", iter_calls(store))
        (out / f"summary-{run_id}.json").write_text(json.dumps(summary, indent=2))
        log(f"[run] done wall={wall:.2f}s spent=${summary['run_spent_usd_from_calls']:.6f} "
            f"calls={summary['run_calls_by_role']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
