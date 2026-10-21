"""Single place for model settings and version strings that make up label_config / cache keys."""
from dataclasses import dataclass, field

TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")

PROMPT_VERSION = "enrich-p1"
SCHEMA_VERSION = "s1"

# USD per 1M tokens, standard tier. Source + date live in cost/rates.csv; keep these in sync.
RATES = {"gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}


@dataclass(frozen=True)
class ModelConfig:
    model: str = "gpt-6-luna"
    effort: str = "none"
    max_batch: int = 50            # contract: <= 50 reviews per enrich request
    out_tokens_per_review: int = 80
    out_tokens_fixed: int = 64
    timeout_s: float = 120.0
    max_transport_retries: int = 3

    @property
    def label_config(self) -> str:
        return f"{self.model}:effort={self.effort}+{PROMPT_VERSION}+{SCHEMA_VERSION}"

    def output_cap(self, n_reviews: int) -> int:
        return self.out_tokens_fixed + self.out_tokens_per_review * n_reviews


def call_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    r = RATES[model]
    return ((input_tokens - cached_tokens) * r["input"] + cached_tokens * r["cached_input"]
            + output_tokens * r["output"]) / 1_000_000
