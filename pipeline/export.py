"""Exports in the grading-contract formats (records.jsonl, calls.jsonl, checkpoints)."""
import gzip
import json
from pathlib import Path

CALL_FIELDS = ("request_id", "role", "review_ids", "model", "phase", "outcome", "label_config",
               "input_tokens", "output_tokens")
EXTRA_CALL_FIELDS = ("run_id", "effort", "attempt", "error", "cached_tokens", "reasoning_tokens",
                     "max_output_tokens", "latency_s", "started_at", "cost_usd", "unknown_charge", "ratelimit")


def iter_records(store, include_synthetic=False):
    rows = store.q("""SELECT r.review_id, r.source_sha256, x.status, x.reason, x.cache_key, x.cache_source_id,
                             x.label_config, c.label, r.synthetic
                      FROM reviews r JOIN temp.scope USING(review_id) LEFT JOIN records x USING(review_id)
                      LEFT JOIN cache.results c ON c.cache_key = x.cache_key
                      ORDER BY r.row_idx""")
    for rid, sha, status, reason, key, src, lc, label, synthetic in rows:
        if synthetic and not include_synthetic:
            continue
        if status == "completed" and label:
            rec = {"review_id": rid, "source_sha256": sha, "status": "completed", **json.loads(label),
                   "label_config": lc}
            if src:
                rec["cache_source_id"] = src
        elif status == "quarantined":
            rec = {"review_id": rid, "source_sha256": sha, "status": "quarantined", "reason": reason}
        else:
            rec = {"review_id": rid, "source_sha256": sha, "status": "quarantined",
                   "reason": "unprocessed_pending"}
        yield rec


def write_jsonl(path, items, gz=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if gz else open
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with opener(tmp, "wt", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False, separators=(",", ":")) + "\n"); n += 1
    tmp.replace(path)
    return n


def iter_calls(store, extra=True, run_ids=None):
    cols = CALL_FIELDS + (EXTRA_CALL_FIELDS if extra else ())
    sql = f"SELECT {','.join(cols)} FROM calls" + (
        f" WHERE run_id IN ({','.join('?' * len(run_ids))})" if run_ids else "") + " ORDER BY started_at"
    for row in store.q(sql, tuple(run_ids or ())):
        d = dict(zip(cols, row))
        d["review_ids"] = json.loads(d["review_ids"]) if d["review_ids"] else []
        if d.get("ratelimit"):
            d["ratelimit"] = json.loads(d["ratelimit"])
        if d["phase"] is None:
            d.pop("phase")
        yield d


def write_checkpoint(store, path):
    ids = store.completed_ids()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps({"completed_ids": ids}, indent=0) + "\n")
    tmp.replace(path)
    return len(ids)
