"""Builds requests. Review text only ever travels inside a JSON data payload, never in instructions."""
import json
from pathlib import Path

from .config import INTENTS, TOPICS

ENRICH_INSTRUCTIONS = (Path(__file__).resolve().parents[1] / "prompts" / "enrich_v1.txt").read_text()

ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "t", "n", "s", "m", "q", "e", "r"],
    "properties": {
        "id": {"type": "string"}, "t": {"type": "string", "enum": list(TOPICS)},
        "n": {"type": "string", "enum": list(INTENTS)}, "s": {"type": "integer"},
        "m": {"type": "number"}, "q": {"type": "string"},
        "e": {"type": "array", "items": {"type": "string"}}, "r": {"type": "boolean"},
    },
}
ENRICH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
                 "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}}}


def enrich_payload(texts, error_note=None):
    """texts: list of review texts. Local ids are '1'..'n' (mapped back to review IDs in code)."""
    data = {"reviews": [{"id": str(i + 1), "text": t} for i, t in enumerate(texts)]}
    if error_note:
        data["previous_error"] = error_note
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
