"""Golden-50 evaluation: Don's human labels vs the pipeline's saved records. No model calls.

  python evals/golden_eval.py --records runs/main/records.jsonl          # or grading/records.jsonl.gz

Only topic / intent / severity are human-labeled. sentiment, evidence_quote, entities and needs_review are
NOT human-labeled; they are never scored against the golden file. Every model evidence_quote is still
checked in code as an exact substring of its source review (for ALL completed records, not just golden).
"""
import argparse
import csv
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_submission import csv_rows  # noqa: E402

TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
HUMAN_FIELDS = ("topic", "intent", "severity")
NOT_HUMAN = ("sentiment", "evidence_quote", "entities", "needs_review")


def open_jsonl(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_golden(path, blank_path):
    rows = list(csv_rows(path))
    blank = {r["review_id"]: r for r in csv_rows(blank_path)}
    problems = []
    if {r["review_id"] for r in rows} != set(blank) or len(rows) != len(blank):
        problems.append("golden IDs differ from golden_50_to_label.csv")
    gold = {}
    for r in rows:
        rid = r["review_id"]
        if rid in blank and r["review_text"] != blank[rid]["review_text"]:
            problems.append(f"{rid}: review_text differs from the original file (spreadsheet edit?)")
        t, n, s = r["topic"].strip().lower(), r["intent"].strip().lower(), r["severity"].strip()
        if t not in TOPICS: problems.append(f"{rid}: invalid human topic {r['topic']!r}")
        if n not in INTENTS: problems.append(f"{rid}: invalid human intent {r['intent']!r}")
        if s not in {"1", "2", "3", "4", "5"}: problems.append(f"{rid}: invalid human severity {r['severity']!r}")
        filled = [f for f in NOT_HUMAN if r.get(f, "").strip()]
        gold[rid] = {"topic": t, "intent": n, "severity": int(s) if s.isdigit() else None,
                     "text": r["review_text"], "extra_fields_filled": filled}
    return gold, problems


def confusion(pairs, labels):
    m = {g: Counter() for g in labels}
    for g, p in pairs:
        m.setdefault(g, Counter())[p] += 1
    cols = list(labels) + ["MISSING"]
    lines = ["| human \\ model | " + " | ".join(map(str, cols)) + " |", "|---" * (len(cols) + 1) + "|"]
    for g in labels:
        lines.append(f"| **{g}** | " + " | ".join(str(m[g][c] or "") for c in cols) + " |")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(ROOT / "data" / "golden_50_labeled.csv"))
    ap.add_argument("--blank", default=str(ROOT / "data" / "golden_50_to_label.csv"))
    ap.add_argument("--records", required=True)
    ap.add_argument("--input", default=str(ROOT / "data" / "spotify_reviews_18months.csv"))
    ap.add_argument("--out", default=str(ROOT / "evals"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    gold, problems = load_golden(a.golden, a.blank)
    texts = {r["review_id"]: r["review_text"] for r in csv_rows(a.input)}
    preds, quote = {}, Counter()
    bad_quotes = []
    for r in open_jsonl(a.records):
        if r["review_id"] in gold:
            preds[r["review_id"]] = r
        if r.get("status") == "completed":
            ok = r["evidence_quote"] in texts.get(r["review_id"], "")
            quote["ok" if ok else "NOT_SUBSTRING"] += 1
            if not ok and len(bad_quotes) < 20:
                bad_quotes.append(r["review_id"])

    rows, pairs = [], {f: [] for f in HUMAN_FIELDS}
    agree = Counter(); n_both = 0; abs_err = 0; sev_diff = Counter()
    for rid, g in gold.items():
        p = preds.get(rid)
        done = p is not None and p.get("status") == "completed"
        row = {"review_id": rid, "model_status": p["status"] if p else "absent",
               "model_reason": (p or {}).get("reason", "")}
        diffs = []
        for f in HUMAN_FIELDS:
            pv = p[f] if done else "MISSING"
            row[f"human_{f}"], row[f"model_{f}"] = g[f], pv
            pairs[f].append((g[f], pv))
            if pv == g[f]:
                agree[f] += 1
            else:
                diffs.append(f)
        if done and g["severity"] is not None:
            n_both += 1; abs_err += abs(p["severity"] - g["severity"]); sev_diff[p["severity"] - g["severity"]] += 1
        row["fields_disagree"] = "|".join(diffs)
        row["model_needs_review"] = p.get("needs_review") if done else ""
        row["model_evidence_quote"] = p.get("evidence_quote") if done else ""
        row["quote_is_exact_substring"] = (p["evidence_quote"] in g["text"]) if done else ""
        row["review_text"] = g["text"]
        rows.append(row)

    n = len(gold)
    completed = sum(1 for r in rows if r["model_status"] == "completed")
    report = {
        "records_file": a.records, "golden_file": a.golden, "golden_count": n,
        "human_labeled_fields": list(HUMAN_FIELDS),
        "not_human_labeled_fields": list(NOT_HUMAN),
        "note": "Don's golden file has only topic/intent/severity filled. sentiment, evidence_quote, entities and "
                "needs_review are not human-labeled and are not scored. Missing/quarantined predictions count as "
                "disagreements (they stay in the denominator).",
        "golden_file_problems": problems,
        "golden_rows_with_unexpected_extra_fields": {rid: g["extra_fields_filled"] for rid, g in gold.items()
                                                     if g["extra_fields_filled"]},
        "model_completed_for_golden": completed,
        "model_missing_or_quarantined": n - completed,
        "agreement": {f: {"agree": agree[f], "of": n, "rate": round(agree[f] / n, 4)} for f in HUMAN_FIELDS},
        "agreement_on_completed_only": {f: round(agree[f] / completed, 4) if completed else None for f in HUMAN_FIELDS},
        "severity_mae_on_completed": round(abs_err / n_both, 4) if n_both else None,
        "severity_model_minus_human": dict(sorted(sev_diff.items())),
        "all_three_agree": sum(1 for r in rows if not r["fields_disagree"]),
        "disagreement_count": sum(1 for r in rows if r["fields_disagree"]),
        "evidence_quote_check_all_completed_records": dict(quote),
        "evidence_quote_failures_first_20": bad_quotes,
    }
    (out / "golden_report.json").write_text(json.dumps(report, indent=2) + "\n")
    with open(out / "golden_disagreements.csv", "w", newline="", encoding="utf-8") as f:
        dis = [r for r in rows if r["fields_disagree"]]
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(dis)
    with open(out / "golden_all.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    L = ["# Golden-50 evaluation", "",
         f"Records: `{a.records}`. Human labels: `{a.golden}`.", "",
         "**Human-labeled fields: topic, intent, severity only.** Don's golden file leaves sentiment, "
         "evidence_quote, entities and needs_review blank, so those fields are *not human-labeled* and are not "
         "scored here. Every model `evidence_quote` is still checked in code as an exact substring of its review.",
         "", f"- Golden rows: {n}; model completed: {completed}; missing/quarantined (counted as wrong): {n - completed}"]
    if problems:
        L += ["- **Golden file problems:** " + "; ".join(problems)]
    for f in HUMAN_FIELDS:
        L.append(f"- {f} agreement: {agree[f]}/{n} = {agree[f] / n:.1%}")
    L += [f"- severity MAE (completed only, n={n_both}): {report['severity_mae_on_completed']}",
          f"- severity model − human: {report['severity_model_minus_human']}",
          f"- all three fields agree: {report['all_three_agree']}/{n}",
          f"- evidence_quote exact-substring check (all completed records): {dict(quote)}", "",
          "## Topic confusion", ""] + confusion(pairs["topic"], TOPICS) + \
         ["", "## Intent confusion", ""] + confusion(pairs["intent"], INTENTS) + \
         ["", "## Severity confusion", ""] + confusion(pairs["severity"], (1, 2, 3, 4, 5)) + \
         ["", f"## Every disagreement ({report['disagreement_count']})", "",
          "| review_id | fields | human t/i/s | model t/i/s | review text |", "|---|---|---|---|---|"]
    for r in rows:
        if r["fields_disagree"]:
            txt = r["review_text"].replace("|", "/").replace("\n", " ")
            L.append(f"| `{r['review_id'][:8]}` | {r['fields_disagree']} | {r['human_topic']}/{r['human_intent']}/"
                     f"{r['human_severity']} | {r['model_topic']}/{r['model_intent']}/{r['model_severity']} | "
                     f"{txt[:160]}{'…' if len(txt) > 160 else ''} |")
    L += ["", "Full rows: `golden_all.csv`; disagreements only: `golden_disagreements.csv`."]
    (out / "golden_report.md").write_text("\n".join(L) + "\n")
    print(json.dumps({k: report[k] for k in ("model_completed_for_golden", "agreement", "severity_mae_on_completed",
                                             "disagreement_count", "golden_file_problems",
                                             "evidence_quote_check_all_completed_records")}, indent=1))


if __name__ == "__main__":
    main()
