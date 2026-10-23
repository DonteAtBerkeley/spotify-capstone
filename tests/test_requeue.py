import json
from dataclasses import replace

from pipeline.enrich import Enricher
from pipeline.export import iter_records
from pipeline.ledger import Ledger
from pipeline.llm import MockClient, Response, default_mock_label
from pipeline.requeue import requeue


def run(store, client, cfg):
    return Enricher(store, client, cfg, Ledger(10), "r", log=lambda m: None, backoff_base=0,
                    rates_model="gpt-6-luna").run()


def capped(ins, p, cap, n):
    """Truncates whenever the cap is below 150 tokens per review (like the real long-review failures)."""
    if cap < 150 * len(p["reviews"]):
        return Response(text='{"items":[', status="incomplete", incomplete_reason="max_output_tokens",
                        input_tokens=50, output_tokens=cap)
    return json.dumps({"items": [default_mock_label(r["id"], r["text"]) for r in p["reviews"]]})


def test_truncation_quarantine_requeue_with_bigger_cap(make_store, cfg):
    store = make_store(["long review one", "long review two", "long review one", "", "fine"])
    run(store, MockClient(capped), cfg)                                   # default cap 80/review -> truncates
    before = {r["review_id"]: r for r in iter_records(store)}
    assert before["r0000"]["reason"] == "validation_failed:malformed_response"
    assert before["r0002"]["reason"] == "same_text_as_quarantined:r0000"
    assert before["r0003"]["reason"] == "empty_review_text"

    dry = requeue(store, ["validation_failed:malformed_response"], "t", dry_run=True)
    assert dry == ["r0000", "r0001", "r0002", "r0004"]                     # alias follows origin; empty never
    assert store.q("SELECT COUNT(*) FROM records WHERE status='quarantined'")[0][0] == 5   # dry run changed nothing

    requeue(store, ["validation_failed:malformed_response"], "t", dry_run=False)
    assert store.q("SELECT COUNT(*) FROM quarantine_history")[0][0] == 4  # history kept, nothing lost
    st = run(store, MockClient(capped), replace(cfg, out_tokens_per_review=160))
    after = {r["review_id"]: r for r in iter_records(store)}
    assert all(after[i]["status"] == "completed" for i in ("r0000", "r0001", "r0002", "r0004"))
    assert after["r0002"]["cache_source_id"] == "r0000"
    assert after["r0003"]["reason"] == "empty_review_text"
    assert st["completed"] == 4 and st["quarantined"] == 0
