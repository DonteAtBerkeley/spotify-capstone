"""Mirrors the real runs: A = subset with interrupt/resume, B = full superset in the SAME state, then export."""
import json

import check_submission as cs
from conftest import write_csv
from pipeline.cli import main


def test_subset_resume_then_superset_export_passes_checker(tmp_path):
    texts = ([f"review {i} the app is bad" if i % 3 else f"review {i} premium is worst" for i in range(150)]
             + ["Good", "Bad app", "Great", "", "Bad app"] * 6)                                 # dups + empties
    full = write_csv(tmp_path / "full.csv", texts)
    sub = write_csv(tmp_path / "sub.csv", texts[:60] + texts[150:160], prefix="r")
    # sub ids must be real full-file ids: rebuild sub from the full file's rows
    rows = full.read_text().splitlines()
    sub.write_text("\n".join([rows[0]] + rows[1:61] + rows[151:161]) + "\n")
    run_dir, g = tmp_path / "main", tmp_path / "grading"
    base = ["run", "--out", str(run_dir), "--batch-size", "10"]
    main(base + ["--input", str(sub), "--run-label", "ckpt", "--stop-after-batches", "2",
                 "--checkpoint-before", str(g / "checkpoint_before.json")])
    main(base + ["--input", str(sub), "--run-label", "ckpt", "--checkpoint-after", str(g / "checkpoint_after.json")])
    main(base + ["--input", str(full), "--run-label", "full", "--workers", "3"])

    ref = cs.reference(str(full), str(full))
    (g / "ingestion.json").write_text(json.dumps(ref["ingestion"]))
    assert main(["export-grading", "--input", str(full), "--run-dir", str(run_dir), "--out", str(g)]) == 0
    report = cs.audit(g, ref)
    assert report["status"] == "pass", (report["issue_counts"], report["examples"])
    cov = report["coverage"]
    assert cov["expected"] == 180 and cov["quarantined"] == 6 and cov["valid_completed"] == 174
    assert cov["valid_cache_reuses"] > 0
