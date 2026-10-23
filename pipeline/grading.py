"""Assemble the contract's grading/ folder from a finished run's state + downstream outputs.
Read-only on the state DB (the input CSV's IDs go into a TEMP scope table; nothing is written to the run)."""
import json
import shutil
from collections import Counter
from pathlib import Path

from .export import iter_calls, iter_records, write_jsonl
from .ingest import csv_rows, file_sha256

COPY_FROM_RUN = ("membership.csv", "ranking.csv", "claims.csv")
KEEP = ("ingestion.json", "checkpoint_before.json", "checkpoint_after.json")


def set_scope(store, csv_path):
    ids = [(r["review_id"],) for r in csv_rows(csv_path)]
    with store.lock:
        store.db.execute("DELETE FROM temp.scope")
        store.db.executemany("INSERT OR IGNORE INTO temp.scope VALUES(?)", ids)
    return len(ids)


def export_grading(store, input_csv, run_dir, out_dir, log=print):
    run_dir, out = Path(run_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = set_scope(store, input_csv)
    run = {"version": "a5-audit-v1", "analysis_count": n, "analysis_sha256": file_sha256(input_csv),
           "classification_input_fields": ["review_text"], "allow_multi_issue": False}
    (out / "run.json").write_text(json.dumps(run, indent=2) + "\n")

    status, reasons = Counter(), Counter()
    def counted(it):
        for r in it:
            status[r["status"] + ("_cache_alias" if r.get("cache_source_id") else "")] += 1
            if r["status"] == "quarantined":
                reasons[r["reason"].split(":")[0]] += 1
            yield r
    if (out / "records.jsonl").exists():
        (out / "records.jsonl").unlink()           # checker flags plain + .gz together as ambiguous
    written = write_jsonl(out / "records.jsonl.gz", counted(iter_records(store)), gz=True)
    calls = write_jsonl(out / "calls.jsonl", iter_calls(store))

    missing = []
    for name in COPY_FROM_RUN:
        if (run_dir / name).exists():
            shutil.copy(run_dir / name, out / name)
        else:
            missing.append(name)
    for name in KEEP:
        if not (out / name).exists():
            missing.append(name)
    summary = {"records": written, "expected": n, "status": dict(status), "quarantine_reasons": dict(reasons),
               "calls": calls, "calls_by_role": dict(Counter(c["role"] for c in iter_calls(store, extra=False))),
               "missing_files": missing}
    log("[grading] " + json.dumps(summary))
    if written != n:
        log(f"[grading] WARNING: wrote {written} records for {n} input IDs")
    if reasons.get("unprocessed_pending"):
        log(f"[grading] WARNING: {reasons['unprocessed_pending']} IDs still pending; finish enrichment first")
    return summary
