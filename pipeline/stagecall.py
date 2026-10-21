"""Shared helper for downstream model roles (verify/group/memo): budget reservation, call log, and an
artifact cache keyed by role + instructions + exact input + model settings (warm runs make no calls)."""
import hashlib
import json
import time

from .config import call_cost
from .llm import TransportError


def stage_call(store, client, ledger, run_id, role, instructions, input_text, schema, cap, review_ids,
               rates_model, log=print):
    key = hashlib.sha256(json.dumps([role, instructions, input_text, client.model, client.effort, schema],
                                    ensure_ascii=False).encode()).hexdigest()
    hit = store.q("SELECT output FROM cache.artifacts WHERE key=?", (key,))
    if hit:
        log(f"[{role}] artifact cache hit: no model call")
        return json.loads(hit[0][0]), True
    est_in = int((len(instructions) + len(input_text)) / 2.0) + 50
    res = ledger.reserve(call_cost(rates_model, est_in, cap))
    t0, started = time.monotonic(), time.time()
    base = {"run_id": run_id, "role": role, "phase": None, "review_ids": review_ids, "model": client.model,
            "effort": client.effort, "label_config": f"{client.model}:effort={client.effort}+{role}-p1",
            "attempt": 1, "max_output_tokens": cap, "started_at": started}
    try:
        resp = client.respond(instructions, input_text, schema, role, cap)
    except TransportError as e:
        ledger.settle(res, None if e.unknown_charge else 0.0)
        store.log_call_now({**base, "request_id": f"failed-{role}-{int(started*1000)}", "outcome": "failed",
                            "error": str(e)[:300], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                            "latency_s": time.monotonic() - t0, "unknown_charge": int(e.unknown_charge)})
        raise
    cost = call_cost(rates_model, resp.input_tokens, resp.output_tokens, resp.cached_tokens)
    ledger.settle(res, cost)
    call = {**base, "request_id": resp.request_id, "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens, "cached_tokens": resp.cached_tokens,
            "reasoning_tokens": resp.reasoning_tokens, "cost_usd": cost, "latency_s": time.monotonic() - t0,
            "ratelimit": resp.ratelimit or None}
    try:
        out = json.loads(resp.text)
        if resp.status != "completed":
            raise ValueError(f"incomplete:{resp.incomplete_reason}")
    except ValueError as e:
        store.log_call_now({**call, "outcome": "failed", "error": str(e)[:300]})
        raise
    def fn(db):
        store.log_call(db, {**call, "outcome": "succeeded"})
        db.execute("INSERT OR REPLACE INTO cache.artifacts VALUES(?,?,?,?,?)",
                   (key, role, json.dumps(out, ensure_ascii=False), resp.request_id, time.time()))
    store.tx(fn)
    return out, False
