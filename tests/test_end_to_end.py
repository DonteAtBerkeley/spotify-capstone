"""Mock end-to-end on cost_100.csv: interrupt -> resume -> full stages -> run the course checker on the export."""
import json
import shutil
from pathlib import Path

import check_submission as cs
from pipeline.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_mock_interrupt_resume_then_checker(tmp_path):
    src = ROOT / "data" / "cost_100.csv"
    out = tmp_path / "run"
    g = tmp_path / "grading"
    args = ["run", "--input", str(src), "--out", str(out), "--batch-size", "20"]
    main(args + ["--stop-after-batches", "2", "--checkpoint-before", str(g / "checkpoint_before.json")])
    before = json.loads((g / "checkpoint_before.json").read_text())["completed_ids"]
    assert len(before) == 40
    main(args + ["--checkpoint-after", str(g / "checkpoint_after.json")])
    after = json.loads((g / "checkpoint_after.json").read_text())["completed_ids"]
    assert set(before) < set(after) and len(after) == 100

    for f in ("records.jsonl", "calls.jsonl", "membership.csv", "ranking.csv", "claims.csv"):
        shutil.copy(out / f, g / f)
    ref = cs.reference(str(src), str(src))
    (g / "run.json").write_text(json.dumps({"version": "a5-audit-v1", "analysis_count": 100,
                                            "analysis_sha256": ref["analysis_sha256"],
                                            "classification_input_fields": ["review_text"], "allow_multi_issue": False}))
    (g / "ingestion.json").write_text(json.dumps(ref["ingestion"]))
    report = cs.audit(g, ref)
    assert report["status"] == "pass", report["issue_counts"]
    assert report["coverage"]["valid_completed"] == 100

    # a third run changes nothing and makes zero calls
    n_calls = sum(1 for _ in open(out / "calls.jsonl"))
    main(args)
    assert sum(1 for _ in open(out / "calls.jsonl")) == n_calls
