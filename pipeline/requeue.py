"""Requeue quarantined records for another enrichment attempt WITHOUT losing history: each record row is
copied into quarantine_history (with the time and original reason) before it is removed from records, which
makes the review pending again. Never touches completed records, empty-text quarantines or the cache.
Run it only when no enrichment run is writing to the same state."""
import time

HISTORY = """CREATE TABLE IF NOT EXISTS quarantine_history(
  review_id TEXT, status TEXT, reason TEXT, cache_key TEXT, cache_source_id TEXT, label_config TEXT,
  attempts INTEGER, run_id TEXT, updated_at REAL, requeued_at REAL, requeue_note TEXT)"""
NEVER = ("empty_review_text",)


def select(store, reasons):
    """reasons: list of reason prefixes, e.g. ['validation_failed:malformed_response']. Rows whose reason is
    same_text_as_quarantined:<origin> follow their origin."""
    rows = store.q("SELECT review_id, reason FROM records WHERE status='quarantined'")
    chosen = {rid for rid, r in rows if any(r.startswith(p) for p in reasons) and r not in NEVER}
    chosen |= {rid for rid, r in rows if r.startswith("same_text_as_quarantined:") and r.split(":", 1)[1] in chosen}
    return sorted(chosen)


def requeue(store, reasons, note, dry_run=True):
    ids = select(store, reasons)
    if dry_run or not ids:
        return ids
    now = time.time()

    def fn(db):
        db.execute(HISTORY)
        db.executemany("""INSERT INTO quarantine_history SELECT *, ?, ? FROM records
                          WHERE review_id=? AND status='quarantined'""", [(now, note, i) for i in ids])
        db.executemany("DELETE FROM records WHERE review_id=? AND status='quarantined'", [(i,) for i in ids])
    store.tx(fn)
    return ids
