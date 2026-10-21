"""Stage 3: independent second labeling of a declared random sample (fixed seed). The verifier sees only
the original text, never the first label. Code compares and reports every disagreement."""
import csv
import hashlib
import math
from pathlib import Path

from .prompts import ENRICH_INSTRUCTIONS, ENRICH_SCHEMA, enrich_payload
from .stagecall import stage_call
from .validate import validate_batch

SEED = "verify-v1"
COMPARE = ("topic", "intent", "severity")


def sample_ids(records, fraction=0.1, minimum=5, maximum=50):
    """Completed originals (not cache aliases), ordered by sha256(seed:id); deterministic."""
    pool = [r for r in records if r["status"] == "completed" and not r.get("cache_source_id")]
    k = min(maximum, len(pool), max(minimum, math.ceil(fraction * len(pool))))
    pool.sort(key=lambda r: hashlib.sha256(f"{SEED}:{r['review_id']}".encode()).hexdigest())
    return [r["review_id"] for r in pool[:k]]


def compare(first, second):
    return [f for f in COMPARE if first.get(f) != second.get(f)]


def run_verify(store, client, ledger, run_id, records, texts, out_dir, rates_model, cap_per=80, log=print, **kw):
    ids = sample_ids(records, **kw)
    by_id = {r["review_id"]: r for r in records}
    sent = [texts[i] for i in ids]
    out, cached = stage_call(store, client, ledger, run_id, "verify", ENRICH_INSTRUCTIONS, enrich_payload(sent),
                             ENRICH_SCHEMA, 64 + cap_per * len(ids), ids, rates_model, log)
    import json
    good, bad, notes = validate_batch(json.dumps(out), sent)
    rows = []
    for i, rid in enumerate(ids):
        second = good.get(str(i + 1))
        diff = compare(by_id[rid], second) if second else ["verifier_invalid:" + bad.get(str(i + 1), "?")]
        rows.append({"review_id": rid, "fields_disagree": "|".join(diff),
                     **{f"first_{f}": by_id[rid].get(f) for f in COMPARE},
                     **{f"verify_{f}": (second or {}).get(f) for f in COMPARE}, "text": texts[rid]})
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "verify_sample.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["review_id"]); w.writeheader(); w.writerows(rows)
    dis = [r for r in rows if r["fields_disagree"]]
    summary = {"seed": SEED, "sample_size": len(ids), "disagreements": len(dis),
               "agreement_by_field": {f: sum(1 for r in rows if f not in r["fields_disagree"]) for f in COMPARE},
               "artifact_cache_hit": cached}
    log(f"[verify] sample={len(ids)} disagreements={len(dis)}")
    return summary, dis
