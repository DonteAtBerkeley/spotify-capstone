"""Stage 1 (code only): CSV -> SQLite. Every source ID gets a row; empty texts are quarantined here."""
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_submission import FIELDS, csv_rows, row_sha  # noqa: E402  (contract's own helpers)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ingest(store, csv_path, run_id="ingest", synthetic=False, chunk=5000):
    """Idempotent: already-ingested IDs are skipped, so resume never re-reads state differently."""
    start = store.q("SELECT COALESCE(MAX(row_idx),-1) FROM reviews")[0][0] + 1
    rows, empties, seen = [], [], 0

    def flush():
        def fn(db):
            db.executemany("INSERT OR IGNORE INTO reviews VALUES(?,?,?,?,?,?,?,?,?)", rows)
            db.executemany("INSERT OR IGNORE INTO temp.scope VALUES(?)", [(r[0],) for r in rows])
            db.executemany("""INSERT OR IGNORE INTO records(review_id,status,reason,run_id,updated_at)
                              VALUES(?, 'quarantined', 'empty_review_text', ?, ?)""", empties)
        store.tx(fn)
        rows.clear(); empties.clear()

    for i, r in enumerate(csv_rows(csv_path)):
        seen += 1
        rows.append((r["review_id"], start + i, row_sha(r), *[r[k] for k in FIELDS[1:]], int(synthetic)))
        if not r["review_text"].strip():
            empties.append((r["review_id"], run_id, time.time()))
        if len(rows) >= chunk:
            flush()
    flush()
    return seen
