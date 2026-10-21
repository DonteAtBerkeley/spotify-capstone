"""Model clients. OpenAIClient talks to the Responses API; MockClient is used by tests and offline runs.
Both return a Response or raise TransportError. Neither ever logs the API key."""
import json
import os
import time
import uuid
from dataclasses import dataclass, field

import requests


@dataclass
class Response:
    text: str
    status: str = "completed"          # completed | incomplete
    incomplete_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    request_id: str = field(default_factory=lambda: "local-" + uuid.uuid4().hex[:16])
    ratelimit: dict = field(default_factory=dict)


class TransportError(Exception):
    def __init__(self, msg, retryable=True, unknown_charge=False, status=None, retry_after=None):
        super().__init__(msg)
        self.retryable, self.unknown_charge, self.status, self.retry_after = retryable, unknown_charge, status, retry_after


class OpenAIClient:
    URL = "https://api.openai.com/v1/responses"
    RL_HEADERS = ("x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
                  "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens")

    def __init__(self, model, effort, timeout_s=120.0):
        from dotenv import load_dotenv
        load_dotenv()
        self._key = os.environ.get("OPENAI_API_KEY")
        if not self._key:
            raise SystemExit("OPENAI_API_KEY is not set (put it in .env).")
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.session = requests.Session()

    def respond(self, instructions, input_text, schema, schema_name, max_output_tokens):
        body = {"model": self.model, "reasoning": {"effort": self.effort}, "instructions": instructions,
                "input": input_text, "max_output_tokens": max_output_tokens, "store": False,
                "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}}}
        try:
            r = self.session.post(self.URL, json=body, timeout=self.timeout_s,
                                  headers={"Authorization": f"Bearer {self._key}"})
        except requests.Timeout as e:
            raise TransportError(f"timeout: {type(e).__name__}", unknown_charge=True) from None
        except requests.RequestException as e:
            raise TransportError(f"network: {type(e).__name__}", unknown_charge=True) from None
        rid = r.headers.get("x-request-id", "")
        rl = {h: r.headers[h] for h in self.RL_HEADERS if h in r.headers}
        if r.status_code != 200:
            retryable = r.status_code in (408, 409, 429) or r.status_code >= 500
            try:
                msg = r.json().get("error", {}).get("message", "")[:200]
            except ValueError:
                msg = r.text[:200]
            ra = r.headers.get("retry-after")
            raise TransportError(f"http {r.status_code}: {msg}", retryable=retryable, status=r.status_code,
                                 retry_after=float(ra) if ra and ra.replace('.', '', 1).isdigit() else None)
        d = r.json()
        text = "".join(c.get("text", "") for o in d.get("output", []) if o.get("type") == "message"
                       for c in o.get("content", []) if c.get("type") == "output_text")
        u = d.get("usage") or {}
        return Response(text=text, status=d.get("status", "completed"),
                        incomplete_reason=(d.get("incomplete_details") or {}).get("reason", ""),
                        input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                        cached_tokens=(u.get("input_tokens_details") or {}).get("cached_tokens", 0),
                        reasoning_tokens=(u.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
                        request_id=rid or d.get("id", ""), ratelimit=rl)


def default_mock_label(local_id, text):
    """Deterministic fake label; quote = first few words, which is always an exact substring."""
    words = text.split()
    quote = text[: text.find(words[min(len(words), 6) - 1]) + len(words[min(len(words), 6) - 1])] if words else text
    low = text.lower()
    neg = any(w in low for w in ("bad", "worst", "hate", "can't", "cannot", "not ", "crash", "premium"))
    return {"id": local_id, "t": "billing" if "premium" in low else "other", "n": "complaint" if neg else "praise",
            "s": 3 if neg else 1, "m": -0.5 if neg else 0.8, "q": quote, "e": [], "r": False}


def default_mock_behavior(instructions, p, cap, n):
    if "reviews" in p:                                   # enrich / verify
        return json.dumps({"items": [default_mock_label(r["id"], r["text"]) for r in p["reviews"]]})
    if "ranking" in p:                                   # memo
        top = p["ranking"][0]["issue_id"] if p["ranking"] else None
        claims = [{"claim_id": "C1", "issue_id": top, "metric": "priority_score"}] if top else []
        return json.dumps({"memo": "Mock memo. Top issue score {C1}." if top else "Mock memo.", "claims": claims})
    return json.dumps({"issues": [{"issue_id": k, "name": "mock " + k} for k in p]})   # group


class MockClient:
    """behavior(instructions, payload_dict, max_output_tokens, call_no) -> str (response text) or raise.
    Default behavior labels every review with default_mock_label."""

    def __init__(self, behavior=None, latency_s=0.0):
        self.behavior = behavior or default_mock_behavior
        self.calls = 0
        self.latency_s = latency_s
        self.model, self.effort = "mock-model", "none"

    def respond(self, instructions, input_text, schema, schema_name, max_output_tokens):
        self.calls += 1
        if self.latency_s:
            time.sleep(self.latency_s)
        out = self.behavior(instructions, json.loads(input_text), max_output_tokens, self.calls)
        if isinstance(out, Response):
            return out
        return Response(text=out, input_tokens=len(instructions + input_text) // 4, output_tokens=len(out) // 4)
