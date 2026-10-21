import json

import pytest

from pipeline.validate import MalformedResponse, recover_quote, validate_batch

TEXTS = ["The app keeps crashing when I open playlists", "Love the lyrics feature"]


def item(i, **kw):
    base = {"id": str(i), "t": "playback", "n": "complaint", "s": 3, "m": -0.6, "q": "keeps crashing", "e": [], "r": False}
    if i == 2:
        base.update(t="catalog", n="praise", s=1, m=0.9, q="lyrics feature", e=["lyrics"])
    base.update(kw)
    return base


def run(items):
    return validate_batch(json.dumps({"items": items}), TEXTS)


def test_good_batch():
    good, bad, notes = run([item(1), item(2)])
    assert set(good) == {"1", "2"} and not bad and not notes
    assert good["2"]["entities"] == ["lyrics"]


@pytest.mark.parametrize("text", ["not json", '{"items": 5}', "[]", '{"items":[{"id":"1"', ""])
def test_malformed_json(text):
    with pytest.raises(MalformedResponse):
        validate_batch(text, TEXTS)


def test_missing_id():
    good, bad, _ = run([item(1)])
    assert bad == {"2": "missing_id"}


def test_foreign_id_ignored_and_noted():
    good, bad, notes = run([item(1), item(2), {**item(1), "id": "999"}, {**item(1), "id": "r0001"}])
    assert set(good) == {"1", "2"} and any("foreign_id:999" in n for n in notes) and len(notes) == 2


def test_duplicate_id_rejected():
    good, bad, notes = run([item(1), item(1), item(2)])
    assert "1" not in good and bad["1"] == "duplicate_id"


def test_bad_quote():
    good, bad, _ = run([item(1, q="crashes all the time"), item(2)])
    assert bad["1"] == "quote_not_in_text"


def test_case_recovered_quote_is_exact_source_span():
    good, _, _ = run([item(1, q="KEEPS CRASHING"), item(2)])
    assert good["1"]["evidence_quote"] == "keeps crashing" and good["1"]["evidence_quote"] in TEXTS[0]


@pytest.mark.parametrize("field,val,reason", [("s", 6, "bad_severity"), ("s", 2.0, "bad_severity"),
                                              ("m", 1.5, "bad_sentiment"), ("t", "ads", "bad_topic"),
                                              ("n", "rant", "bad_intent"), ("r", "no", "bad_needs_review"),
                                              ("e", "x", "bad_entities")])
def test_out_of_range(field, val, reason):
    _, bad, _ = run([item(1, **{field: val}), item(2)])
    assert bad["1"].startswith(reason)


def test_entities_must_be_literal():
    good, _, _ = run([item(1, e=["playlists", "Spotify Wrapped"]), item(2)])
    assert good["1"]["entities"] == ["playlists"]


def test_recover_quote_rejects_blank():
    assert recover_quote("  ", "abc") is None
