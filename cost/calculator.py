"""100-review cost/runtime calculator. OFFLINE by default: reads saved measurements, makes no API calls,
needs no key. Importing this module does nothing.

  python cost/calculator.py                 # offline replay -> cost/usage.csv + cost/report.md
  python cost/calculator.py --rates other_rates.csv --assumptions a.json --out /tmp/x
  python cost/calculator.py collect         # (after a pilot) copy pilot outputs into cost/*.jsonl
"""
import argparse
import csv
import glob
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


# -- inputs ------------------------------------------------------------------
def load_rates(path):
    rates = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rates[(r["model"], r["tier"], r["item"])] = float(r["price_usd_per_million_units"]) / 1_000_000
    return rates


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


# -- arithmetic --------------------------------------------------------------
def billed_items(call):
    """Mutually exclusive billing items. Cached input is subtracted from input before the uncached rate."""
    cached = call.get("cached_tokens") or 0
    return {"input_tokens_uncached": call["input_tokens"] - cached, "input_tokens_cached": cached,
            "output_tokens": call["output_tokens"]}


def call_cost(call, rates, tier="standard"):
    total = 0.0
    for item, units in billed_items(call).items():
        if units:
            total += units * rates[(call["model"], tier, item)]
    return total


def usage_rows(calls, rates):
    rows = []
    for c in calls:
        for item, units in billed_items(c).items():
            price = rates.get((c["model"], "standard", item), 0.0)
            rows.append({"run_id": c["run_id"], "request_id": c["request_id"], "role": c["role"],
                         "outcome": c["outcome"], "model": c["model"], "item": item, "units": units,
                         "unit": "token", "price_usd_per_unit": f"{price:.10f}",
                         "item_cost_usd": f"{units * price:.10f}",
                         "unknown_charge": c.get("unknown_charge", 0)})
    return rows


def measure(calls, run, rates):
    by_role = defaultdict(lambda: {"requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                                   "cached_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0, "latency_s": 0.0,
                                   "reviews_sent": 0})
    for c in calls:
        s = by_role[c["role"]]
        s["requests"] += 1
        s["failed"] += c["outcome"] != "succeeded"
        for k in ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"):
            s[k] += c.get(k) or 0
        s["cost_usd"] += call_cost(c, rates)
        s["latency_s"] += c.get("latency_s") or 0
        s["reviews_sent"] += len(c["review_ids"])
    total = sum(s["cost_usd"] for s in by_role.values())
    return {"run_id": run["run_id"], "wall_s": run["wall_s"], "stage_s": run["stage_s"], "by_role": dict(by_role),
            "api_cost_usd": total, "unknown_charge_calls": sum(c.get("unknown_charge", 0) for c in calls),
            **{k: run.get(k) for k in ("completed", "quarantined", "rows", "unique_texts", "cache_hits",
                                       "distinct_sent", "settings")}}


def estimate(cold, a, rates, ratelimits):
    en = cold["by_role"].get("enrich", {})
    sent = cold["distinct_sent"] or 1
    per_text = en.get("cost_usd", 0) / sent
    texts = a["distinct_nonempty_texts"] if a["use_exact_text_reuse"] else a["nonempty_rows"]
    verify = cold["by_role"].get("verify", {})
    per_verify = verify.get("cost_usd", 0) / max(1, verify.get("reviews_sent", 1))
    fixed = sum(cold["by_role"].get(r, {}).get("cost_usd", 0) for r in ("group", "memo"))
    base_enrich = per_text * texts
    base = base_enrich + per_verify * a["verify_sample_size"] + fixed
    cons = base_enrich * a["conservative_enrich_multiplier"] + per_verify * a["verify_sample_size"] * 2 + fixed * 2
    no_reuse = per_text * a["nonempty_rows"] + per_verify * a["verify_sample_size"] + fixed
    # batch-API scenario: same tokens, batch rates (hypothetical, not used)
    tok_in, tok_out = en.get("input_tokens", 0) / sent, en.get("output_tokens", 0) / sent
    batch_rate_in = rates.get(("gpt-6-luna", "batch", "input_tokens_uncached"))
    batch_rate_out = rates.get(("gpt-6-luna", "batch", "output_tokens"))
    batch_enrich = texts * (tok_in * batch_rate_in + tok_out * batch_rate_out) if batch_rate_in else None

    # time: enrichment throughput per worker measured on the pilot (1 worker); multi-worker is MODELED
    enrich_s = cold["stage_s"].get("enrich") or 0
    per_worker_rpm = sent / enrich_s * 60 if enrich_s else None          # reviews/min, 1 worker
    req_per_min_worker = en["requests"] / enrich_s * 60 if enrich_s else None
    tokens_per_req_ratelimited = (en["input_tokens"] / en["requests"]
                                  + a["max_output_tokens_per_review"] * 50 + 64) if en.get("requests") else None
    rpm_lim = a["rate_limit_rpm"] or ratelimits.get("rpm")
    tpm_lim = a["rate_limit_tpm"] or ratelimits.get("tpm")
    max_workers_tpm = math.floor(tpm_lim / (req_per_min_worker * tokens_per_req_ratelimited)) if tpm_lim and req_per_min_worker else None
    max_workers_rpm = math.floor(rpm_lim / req_per_min_worker) if rpm_lim and req_per_min_worker else None
    w = a["workers"]
    eff_w = min(x for x in (w, max_workers_tpm, max_workers_rpm) if x)
    modeled_rpm = per_worker_rpm * eff_w if per_worker_rpm else None
    downstream_s = sum(cold["stage_s"].get(k, 0) for k in ("verify", "group", "rank", "memo"))
    enrich_full_s = texts / modeled_rpm * 60 if modeled_rpm else None
    ingest_s = a.get("full_ingest_seconds")
    total_s = (enrich_full_s + downstream_s + ingest_s) if (enrich_full_s and ingest_s is not None) else None
    return {"texts_to_enrich": texts, "per_text_enrich_usd": per_text, "base_usd": base, "conservative_usd": cons,
            "no_reuse_usd": no_reuse, "batch_scenario_enrich_usd": batch_enrich, "base_enrich_usd": base_enrich,
            "per_verify_review_usd": per_verify, "fixed_group_memo_usd": fixed,
            "per_worker_reviews_per_min": per_worker_rpm, "req_per_min_per_worker": req_per_min_worker,
            "tokens_per_request_for_tpm": tokens_per_req_ratelimited, "max_workers_by_tpm": max_workers_tpm,
            "max_workers_by_rpm": max_workers_rpm, "workers": w, "effective_workers": eff_w,
            "modeled_reviews_per_min": modeled_rpm, "enrich_hours": enrich_full_s / 3600 if enrich_full_s else None,
            "ingest_s": ingest_s, "downstream_s": downstream_s,
            "total_hours": total_s / 3600 if total_s else None,
            "over_budget_base": base > a["budget_usd"], "over_budget_conservative": cons > a["budget_usd"]}


# -- report ------------------------------------------------------------------
def fmt(x, nd=6):
    if x is None:
        return "unknown"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render(cold, warm, est, a, inputs, ratelimits):
    L = ["# 100-review pilot: measured cost/runtime + full-run estimate", "",
         "Generated offline by `python cost/calculator.py` from `pilot_calls.jsonl`, `pilot_runs.json`, "
         "`rates.csv`, `assumptions.json`. No API calls. Formula per call: "
         "`item_cost = billed_units x price_per_unit`, `total = sum(item_cost)`; "
         "uncached input = input_tokens - cached_tokens.", "",
         "## Measured on the pilot (cost_100.csv)", "",
         f"- Input: `{inputs['input']}` sha256 `{inputs['sha256']}` (matches manifest.json: {inputs['sha_ok']}); "
         f"100 IDs match cost_100.csv: {inputs['ids_ok']}",
         f"- Settings: {json.dumps(cold['settings'])}",
         f"- Rate-limit headers seen: {json.dumps(ratelimits)}", "",
         "| | Cold run | Warm run |", "|---|---|---|"]
    def row(name, f):
        L.append(f"| {name} | {f(cold)} | {f(warm)} |")
    row("run_id", lambda m: f"`{m['run_id']}`")
    row("rows / completed / quarantined", lambda m: f"{m['rows']} / {m['completed']} / {m['quarantined']}")
    row("unique texts / result-cache hits", lambda m: f"{m['unique_texts']} / {m['cache_hits']}")
    for role in ("enrich", "verify", "group", "memo"):
        row(f"{role}: requests (failed)", lambda m, r=role: f"{m['by_role'].get(r, {}).get('requests', 0)} "
                                                            f"({m['by_role'].get(r, {}).get('failed', 0)})")
        row(f"{role}: in / out / cached tokens", lambda m, r=role: "{} / {} / {}".format(
            *(m['by_role'].get(r, {}).get(k, 0) for k in ("input_tokens", "output_tokens", "cached_tokens"))))
        row(f"{role}: API cost USD", lambda m, r=role: fmt(m['by_role'].get(r, {}).get('cost_usd', 0.0)))
    row("**total API cost USD**", lambda m: f"**{fmt(m['api_cost_usd'])}**")
    row("calls with unknown charge (timeouts)", lambda m: m["unknown_charge_calls"])
    row("wall-clock s (end to end)", lambda m: fmt(m["wall_s"], 2))
    row("stage s", lambda m: ", ".join(f"{k} {v:.2f}" for k, v in m["stage_s"].items()) or "-")
    row("cost per 1,000 input rows USD", lambda m: fmt(m["api_cost_usd"] / m["rows"] * 1000))
    row("cost per completed record USD", lambda m: fmt(m["api_cost_usd"] / m["completed"] if m["completed"] else None))
    row("enrich throughput (reviews/min, 1 worker)",
        lambda m: fmt(m["distinct_sent"] / m["stage_s"]["enrich"] * 60, 1) if m["distinct_sent"] and m["stage_s"].get("enrich") else "n/a (0 sent)")
    L += ["", "Local compute: " + ("unknown (not measured); no API charge" if a["local_compute_usd"] is None
                                   else f"${a['local_compute_usd']}") + ". Shown separately from API spend.", "",
          "## Full-run estimate (spotify_reviews_18months.csv)", "",
          f"- Rows accounted: {a['full_rows']:,} = {a['nonempty_rows']:,} nonempty outputs + "
          f"{a['empty_text_quarantines']} empty-text quarantines",
          f"- Texts to enrich: {est['texts_to_enrich']:,} "
          f"({'exact-text reuse ON' if a['use_exact_text_reuse'] else 'reuse OFF'})",
          f"- Measured enrich cost per distinct text (incl. pilot retries): ${fmt(est['per_text_enrich_usd'], 8)}",
          f"- Verify sample {a['verify_sample_size']} x ${fmt(est['per_verify_review_usd'], 8)}; "
          f"group+memo fixed overhead ${fmt(est['fixed_group_memo_usd'])} (added once, not per review)",
          f"- Fallback: max fraction {a['max_fallback_fraction']} (model: {a['fallback_model']})",
          f"- Output-token cap: {a['max_output_tokens_per_review']}/review (+64 per request)", "",
          "| Scenario | API cost USD |", "|---|---|",
          f"| Base (reuse ON, measured mix) | {fmt(est['base_usd'], 2)} |",
          f"| Conservative (enrich x{a['conservative_enrich_multiplier']}, verify/group/memo x2) | {fmt(est['conservative_usd'], 2)} |",
          f"| No-reuse comparison ({a['nonempty_rows']:,} texts) | {fmt(est['no_reuse_usd'], 2)} |",
          f"| Batch API scenario, enrich only (NOT used; hypothetical) | {fmt(est['batch_scenario_enrich_usd'], 2)} |",
          f"| Budget | {a['budget_usd']:.2f} |", ""]
    if est["over_budget_base"]:
        L.append(f"> **WARNING: base scenario exceeds the ${a['budget_usd']:.2f} budget.**")
    if est["over_budget_conservative"]:
        L.append(f"> **WARNING: conservative scenario exceeds the ${a['budget_usd']:.2f} budget.** "
                 "The run's spend ledger stops admitting batches at the cap; progress is saved and resumable.")
    L += ["", "### Time (MODELED: only 1 worker was measured)", "",
          f"- Measured per worker: {fmt(est['per_worker_reviews_per_min'], 1)} reviews/min, "
          f"{fmt(est['req_per_min_per_worker'], 2)} requests/min",
          f"- Rate-limit ceiling: tokens counted per request ~{fmt(est['tokens_per_request_for_tpm'], 0)} "
          f"(input + max_output_tokens) -> max workers by TPM {fmt(est['max_workers_by_tpm'])}, "
          f"by RPM {fmt(est['max_workers_by_rpm'])}",
          f"- Chosen workers: {est['workers']} (effective {est['effective_workers']}) -> "
          f"modeled {fmt(est['modeled_reviews_per_min'], 0)} distinct reviews/min (linear scaling assumed)",
          f"- Enrichment: {fmt(est['enrich_hours'], 2)} h; ingest {fmt(est['ingest_s'], 1)} s; "
          f"downstream (measured once) {fmt(est['downstream_s'], 1)} s; total {fmt(est['total_hours'], 2)} h",
          "- Parallelism shortens elapsed time; it does not lower cost per classification. "
          "Rate limits, retries and provider latency can make real throughput lower than modeled.", "",
          "## Controls demonstrated", "",
          "- Shared spend ledger reserves worst-case cost before each call; admission stops at cap (tests/test_enrich.py::test_budget_cap_stops_admission).",
          "- Bounded retries with backoff+jitter; timeouts flagged `unknown_charge` (test_transport_*, test_timeout_flags_unknown_charge).",
          "- Atomic per-batch save; interrupt/resume with zero re-enrichment (test_interrupt_and_resume_no_reenrichment, test_end_to_end).",
          "- Exact-text result cache: warm run made 0 enrich calls (table above)."]
    return "\n".join(L) + "\n"


def replay(rates_path, assumptions_path, out_dir, src=HERE):
    rates = load_rates(rates_path)
    a = json.loads(Path(assumptions_path).read_text())
    calls = load_jsonl(src / "pilot_calls.jsonl")
    runs = json.loads((src / "pilot_runs.json").read_text())
    cold_run, warm_run = runs["cold"], runs["warm"]
    cold = measure([c for c in calls if c["run_id"] == cold_run["run_id"]], cold_run, rates)
    warm = measure([c for c in calls if c["run_id"] == warm_run["run_id"]], warm_run, rates)
    rl = next((c["ratelimit"] for c in calls if c.get("ratelimit")), {})
    ratelimits = {"rpm": int(rl["x-ratelimit-limit-requests"]) if "x-ratelimit-limit-requests" in rl else None,
                  "tpm": int(rl["x-ratelimit-limit-tokens"]) if "x-ratelimit-limit-tokens" in rl else None}
    est = estimate(cold, a, rates, ratelimits)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rows = usage_rows(calls, rates)
    with open(out_dir / "usage.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["run_id"]); w.writeheader(); w.writerows(rows)
    (out_dir / "report.md").write_text(render(cold, warm, est, a, runs["inputs"], ratelimits))
    result = {"cold": cold, "warm": warm, "estimate": est}
    (out_dir / "replay.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def collect(pilot_dir=HERE / "pilot"):
    """Copy measured pilot outputs (cold + warm) into the submitted cost/ files."""
    import hashlib, sys
    sys.path.insert(0, str(HERE.parent))
    from check_submission import csv_rows
    runs = {}
    calls = []
    for name in ("cold", "warm"):
        d = pilot_dir / name
        summary = json.loads(Path(sorted(glob.glob(str(d / "summary-*.json")))[-1]).read_text())
        recs = load_jsonl(d / "records.jsonl")
        texts = {r["review_id"]: r["review_text"] for r in csv_rows(summary["preflight"]["input"])}
        pre, en = summary["preflight"], summary.get("enrich", {})
        runs[name] = {"run_id": pre["run_id"], "wall_s": summary["wall_s"], "stage_s": summary["stage_s"],
                      "rows": len(recs), "completed": sum(r["status"] == "completed" for r in recs),
                      "quarantined": sum(r["status"] == "quarantined" for r in recs),
                      "unique_texts": len(set(texts.values())), "cache_hits": en.get("cache_hits", 0),
                      "distinct_sent": pre["distinct_texts_to_send"],
                      "settings": {k: pre[k] for k in ("model", "effort", "label_config", "batch_size", "workers",
                                                        "budget_cap_usd")},
                      "spent_ledger_usd": summary["ledger"]["spent"], "summary_file": str(Path(d.name) / Path(
                          sorted(glob.glob(str(d / "summary-*.json")))[-1]).name)}
        calls += [c for c in load_jsonl(d / "calls.jsonl") if c["run_id"] == pre["run_id"]]
        if name == "cold":
            shutil.copy(d / "records.jsonl", HERE / "pilot_records.jsonl")
            input_path = pre["input"]
    manifest = json.loads((HERE.parent / "manifest.json").read_text())
    sha = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    ids = [r["review_id"] for r in csv_rows(input_path)]
    pilot_ids = [r["review_id"] for r in load_jsonl(HERE / "pilot_records.jsonl")]
    runs["inputs"] = {"input": input_path, "sha256": sha, "sha_ok": sha == manifest["files"]["cost_100.csv"]["sha256"],
                      "ids_ok": ids == pilot_ids and len(ids) == 100}
    (HERE / "pilot_runs.json").write_text(json.dumps(runs, indent=2))
    with open(HERE / "pilot_calls.jsonl", "w") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"collected {len(calls)} calls; cold={runs['cold']['run_id']} warm={runs['warm']['run_id']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="replay", choices=["replay", "collect"])
    ap.add_argument("--rates", default=str(HERE / "rates.csv"))
    ap.add_argument("--assumptions", default=str(HERE / "assumptions.json"))
    ap.add_argument("--out", default=str(HERE))
    args = ap.parse_args()
    if args.cmd == "collect":
        collect()
    else:
        r = replay(args.rates, args.assumptions, args.out)
        e = r["estimate"]
        print(f"cold API ${r['cold']['api_cost_usd']:.6f} wall {r['cold']['wall_s']}s | "
              f"warm API ${r['warm']['api_cost_usd']:.6f} wall {r['warm']['wall_s']}s | "
              f"full base ${e['base_usd']:.2f} conservative ${e['conservative_usd']:.2f} | "
              f"report -> {Path(args.out) / 'report.md'}")
