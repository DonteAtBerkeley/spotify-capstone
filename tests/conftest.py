import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.config import ModelConfig  # noqa: E402
from pipeline.ingest import ingest  # noqa: E402
from pipeline.ledger import Ledger  # noqa: E402
from pipeline.store import Store  # noqa: E402

FIELDS = ["review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp"]


def write_csv(path, texts, prefix="r"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        for i, t in enumerate(texts):
            w.writerow([f"{prefix}{i:04d}", t, "1", "0", "", "2023-01-01 00:00:00"])
    return path


@pytest.fixture
def make_store(tmp_path):
    def _make(texts, name="s", cache="cache", synthetic=False):
        store = Store(tmp_path / f"{name}.sqlite", tmp_path / f"{cache}.sqlite")
        ingest(store, write_csv(tmp_path / f"{name}.csv", texts), synthetic=synthetic)
        return store
    return _make


@pytest.fixture
def cfg():
    return ModelConfig(model="mock-model", max_batch=50, max_transport_retries=2)


@pytest.fixture
def ledger():
    return Ledger(10.0)
