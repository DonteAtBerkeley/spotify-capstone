"""Code validation of model output. The model is never trusted for IDs, ranges, enums or quotes."""
import json
import math

from .config import INTENTS, TOPICS


class MalformedResponse(Exception):
    pass


def parse_items(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as e:
        raise MalformedResponse(f"invalid JSON: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise MalformedResponse("missing 'items' list")
    return data["items"]


def recover_quote(quote, text):
    """Exact substring wins. Otherwise accept only a case-insensitive exact-span match and return the
    span copied from the source, so the saved quote is always a true substring."""
    if quote and quote.strip() and quote in text:
        return quote
    if quote and quote.strip():
        i = text.lower().find(quote.lower())
        if i >= 0 and len(text.lower()) == len(text):     # lower() kept offsets aligned
            return text[i:i + len(quote)]
    return None


def validate_item(item, text):
    """Returns (label_dict, None) or (None, error_reason)."""
    if not isinstance(item, dict):
        return None, "item_not_object"
    t, n, s, m = item.get("t"), item.get("n"), item.get("s"), item.get("m")
    if t not in TOPICS:
        return None, f"bad_topic:{str(t)[:20]}"
    if n not in INTENTS:
        return None, f"bad_intent:{str(n)[:20]}"
    if type(s) is not int or not 1 <= s <= 5:
        return None, f"bad_severity:{str(s)[:10]}"
    if type(m) not in (int, float) or not math.isfinite(m) or not -1 <= m <= 1:
        return None, f"bad_sentiment:{str(m)[:10]}"
    if type(item.get("r")) is not bool:
        return None, "bad_needs_review"
    ents = item.get("e")
    if not isinstance(ents, list) or not all(isinstance(x, str) for x in ents):
        return None, "bad_entities"
    quote = recover_quote(item.get("q"), text)
    if quote is None:
        return None, "quote_not_in_text"
    low = text.lower()
    ents = [x for x in dict.fromkeys(x.strip() for x in ents) if x and x.lower() in low]   # literal only
    return {"topic": t, "intent": n, "sentiment": round(float(m), 3), "severity": s, "entities": ents,
            "evidence_quote": quote, "needs_review": item["r"]}, None


def validate_batch(text, sent_texts):
    """sent_texts: list of texts sent with local ids '1'..'n'.
    Returns (good: {local_id: label}, bad: {local_id: reason}, notes: [str]). Raises MalformedResponse."""
    items = parse_items(text)
    expected = {str(i + 1) for i in range(len(sent_texts))}
    good, bad, notes, seen = {}, {}, [], set()
    for item in items:
        lid = str(item.get("id")) if isinstance(item, dict) else None
        if lid not in expected:
            notes.append(f"foreign_id:{str(lid)[:40]}")
            continue
        if lid in seen:
            notes.append(f"duplicate_id:{lid}")
            good.pop(lid, None)
            bad[lid] = "duplicate_id"
            continue
        seen.add(lid)
        label, err = validate_item(item, sent_texts[int(lid) - 1])
        if err:
            bad[lid] = err
        else:
            good[lid] = label
    for lid in expected - seen:
        bad[lid] = "missing_id"
    return good, bad, notes
