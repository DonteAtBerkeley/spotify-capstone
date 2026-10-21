import csv
import json
import sys
from pathlib import Path

from conftest import write_csv
from pipeline.enrich import Enricher
from pipeline.export import iter_calls, iter_records
from pipeline.ingest import ingest
from pipeline.ledger import Ledger
from pipeline.llm import MockClient
from pipeline.store import Store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cost"))
import calculator  # noqa: E402


def test_subset_then_superset_share_one_state(tmp_path, cfg):
    texts = [f"text {i}" for i in range(120)]
    full = write_csv(tmp_path / "full.csv", texts)
    sub = write_csv(tmp_path / "sub.csv", texts[:30])
    run = lambda store, c: Enricher(store, c, cfg, Ledger(10), "x", log=lambda m: None, rates_model="gpt-6-luna").run()
    s1 = Store(tmp_path / "st.sqlite", tmp_path / "c.sqlite"); ingest(s1, sub)
    c1 = MockClient(); run(s1, c1)
    assert c1.calls == 1 and len(list(iter_records(s1))) == 30
    s2 = Store(tmp_path / "st.sqlite", tmp_path / "c.sqlite"); ingest(s2, full)   # new process, same state
    c2 = MockClient(); st = run(s2, c2)
    assert st["phase"] == "resume" and c2.calls == 2
    sent_later = {i for c in iter_calls(s2) if c["phase"] == "resume" for i in c["review_ids"]}
    assert not sent_later & {f"r{i:04d}" for i in range(30)}
    assert len(list(iter_records(s2))) == 120 and len(s2.completed_ids()) == 120


def test_calculator_offline_and_rate_doubling(tmp_path):
    if not (ROOT / "cost" / "pilot_calls.jsonl").exists():
        import pytest; pytest.skip("pilot not collected")
    base = calculator.replay(ROOT / "cost" / "rates.csv", ROOT / "cost" / "assumptions.json", tmp_path / "a")
    doubled = tmp_path / "rates2.csv"
    with open(ROOT / "cost" / "rates.csv", newline="") as f, open(doubled, "w", newline="") as g:
        rows = list(csv.DictReader(f))
        w = csv.DictWriter(g, fieldnames=list(rows[0])); w.writeheader()
        for r in rows:
            r["price_usd_per_million_units"] = str(float(r["price_usd_per_million_units"]) * 2); w.writerow(r)
    dbl = calculator.replay(doubled, ROOT / "cost" / "assumptions.json", tmp_path / "b")
    assert abs(dbl["cold"]["api_cost_usd"] - 2 * base["cold"]["api_cost_usd"]) < 1e-12
    assert abs(dbl["estimate"]["base_usd"] - 2 * base["estimate"]["base_usd"]) < 1e-9
    assert dbl["cold"]["wall_s"] == base["cold"]["wall_s"]
    assert dbl["estimate"]["enrich_hours"] == base["estimate"]["enrich_hours"]
    # changing projected record count must not change measured pilot results
    a = json.loads((ROOT / "cost" / "assumptions.json").read_text()); a["distinct_nonempty_texts"] = 1000
    (tmp_path / "a2.json").write_text(json.dumps(a))
    small = calculator.replay(ROOT / "cost" / "rates.csv", tmp_path / "a2.json", tmp_path / "c")
    assert small["cold"] == base["cold"] and small["estimate"]["base_usd"] < base["estimate"]["base_usd"]
