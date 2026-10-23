import copy
import json

import pytest

from check_submission import mean_string
from pipeline.enrich import Enricher
from pipeline.export import iter_records
from pipeline.ledger import BudgetExceeded, Ledger
from pipeline.llm import MockClient, default_mock_behavior
from pipeline.memo import MemoRejected, build_pack, check_and_render
from pipeline.rank import mean_str, rank
from pipeline.verify import run_verify, sample_ids


def test_ledger_reservations():
    led = Ledger(1.0)
    a = led.reserve(0.6)
    with pytest.raises(BudgetExceeded):
        led.reserve(0.5)
    led.settle(a, 0.1)
    led.reserve(0.5)
    assert led.snapshot() == {"cap": 1.0, "spent": 0.1, "reserved": 0.5}
    led.settle(0.5, None)              # unknown charge books the full reservation
    assert led.snapshot()["spent"] == 0.6


def test_rank_matches_contract():
    pairs = [("ISS-b", "1"), ("ISS-b", "2"), ("ISS-a", "3"), ("ISS-a", "4"), ("ISS-c", "5")]
    sev = {"1": 4, "2": 1, "3": 3, "4": 2, "5": 2}
    rows = rank(pairs, sev)
    assert [(r["rank"], r["issue_id"], r["priority_score"]) for r in rows] == [(1, "ISS-a", 5), (2, "ISS-b", 5), (3, "ISS-c", 2)]
    for total, n in [(2, 3), (5, 3), (1, 8), (7, 6), (10, 3)]:
        assert mean_str(total, n) == mean_string(total, n)
    assert mean_str(1, 8) == "0.125000" and mean_str(2, 3) == "0.666667"


def make_enriched(make_store, cfg, texts):
    store = make_store(texts)
    Enricher(store, MockClient(), cfg, Ledger(10), "t", log=lambda m: None, rates_model="gpt-6-luna").run()
    return store


def test_planted_wrong_label_caught_by_verifier(make_store, cfg, tmp_path):
    texts = [f"Premium is too expensive and the app is bad {i}" for i in range(20)]
    store = make_enriched(make_store, cfg, texts)
    records = list(iter_records(store))
    texts_by_id = dict(store.q("SELECT review_id, review_text FROM reviews"))
    sample = sample_ids(records)
    planted = copy.deepcopy(records)                     # separate test copy; real records untouched
    target = next(r for r in planted if r["review_id"] == sample[0])
    target.update(topic="catalog", intent="praise", severity=5)
    summary, dis = run_verify(store, MockClient(), Ledger(10), "v", planted, texts_by_id, tmp_path, "gpt-6-luna",
                              log=lambda m: None)
    assert [d["review_id"] for d in dis] == [sample[0]]
    assert set(dis[0]["fields_disagree"].split("|")) == {"topic", "intent", "severity"}
    assert summary["sample_size"] == len(sample) >= 5
    assert all(r["topic"] != "catalog" for r in records)    # the real records were not modified


def test_verifier_sees_text_only_not_first_label(make_store, cfg, tmp_path):
    store = make_enriched(make_store, cfg, [f"bad app {i}" for i in range(10)])
    records = list(iter_records(store))
    seen = {}
    def spy(ins, p, cap, n):
        seen["p"] = p
        return default_mock_behavior(ins, p, cap, n)
    run_verify(store, MockClient(spy), Ledger(10), "v", records, dict(store.q("SELECT review_id, review_text FROM reviews")),
               tmp_path, "gpt-6-luna", log=lambda m: None)
    assert set(seen["p"]) == {"reviews"} and all(set(r) == {"id", "text"} for r in seen["p"]["reviews"])


RANKING = [{"rank": 1, "issue_id": "ISS-billing", "complaint_count": 13, "severity_sum": 39,
            "mean_severity": "3.000000", "priority_score": 39}]
PACK = {"evidence": [{"issue_id": "ISS-billing", "review_id": "abc", "quote": "too expensive"}]}


def test_memo_numbers_filled_by_code():
    text, claims = check_and_render({"memo": "Billing leads with {C1} [review:abc].",
                                     "claims": [{"claim_id": "C1", "issue_id": "ISS-billing", "metric": "severity_sum"}]},
                                    RANKING, PACK)
    assert "39 [C1]" in text and claims["C1"] == ("ISS-billing", "severity_sum", "39")


OK_CLAIM = [{"claim_id": "C1", "issue_id": "ISS-billing", "metric": "priority_score"}]


@pytest.mark.parametrize("memo,claims,msg", [
    ("Billing {C1} has 40 complaints.", OK_CLAIM, "raw digits"),
    ("Billing {C1}. See [review:zzz].", OK_CLAIM, "not in evidence pack"),
    ("Score {C1} and {C2}.", OK_CLAIM, "has no claim"),
    ("x", [{"claim_id": "C1", "issue_id": "ISS-made-up", "metric": "priority_score"}], "unknown issue"),
    ("Billing matters most.", [], "declares no claims"),
    ("Billing leads {C1}.", OK_CLAIM + [{"claim_id": "C2", "issue_id": "ISS-billing", "metric": "mean_severity"}],
     r"not cited in memo text: \['C2'\]"),
])
def test_memo_rejections(memo, claims, msg):
    with pytest.raises(MemoRejected, match=msg):
        check_and_render({"memo": memo, "claims": claims}, RANKING, PACK)
