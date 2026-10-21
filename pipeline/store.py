"""SQLite state. Run state (reviews, records, calls) lives in one file; the exact-text result cache in
another, ATTACHed so a batch's cache rows and record rows commit in ONE transaction."""
import json
import sqlite3
import threading
import time
from pathlib import Path

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews(
  review_id TEXT PRIMARY KEY, row_idx INTEGER, source_sha256 TEXT, review_text TEXT,
  review_rating TEXT, review_likes TEXT, app_version TEXT, review_timestamp TEXT,
  synthetic INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS records(
  review_id TEXT PRIMARY KEY, status TEXT, reason TEXT, cache_key TEXT, cache_source_id TEXT,
  label_config TEXT, attempts INTEGER DEFAULT 0, run_id TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS calls(
  request_id TEXT PRIMARY KEY, run_id TEXT, role TEXT, phase TEXT, review_ids TEXT, model TEXT,
  effort TEXT, label_config TEXT, outcome TEXT, error TEXT, attempt INTEGER, input_tokens INTEGER,
  output_tokens INTEGER, cached_tokens INTEGER, reasoning_tokens INTEGER, max_output_tokens INTEGER,
  latency_s REAL, started_at REAL, cost_usd REAL, unknown_charge INTEGER DEFAULT 0, ratelimit TEXT);
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, command TEXT, input_path TEXT, started_at REAL, ended_at REAL,
  wall_s REAL, summary TEXT);
"""
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache.results(
  cache_key TEXT PRIMARY KEY, label_config TEXT, label TEXT, origin_review_id TEXT,
  request_id TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS cache.artifacts(
  key TEXT PRIMARY KEY, role TEXT, output TEXT, request_id TEXT, created_at REAL);
"""


class Store:
    def __init__(self, state_path, cache_path):
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        # Rollback journal (not WAL) so commits across the attached DB are atomic.
        self.db = sqlite3.connect(str(state_path), check_same_thread=False, isolation_level=None)
        self.db.execute("ATTACH DATABASE ? AS cache", (str(cache_path),))
        self.db.executescript(STATE_SCHEMA + CACHE_SCHEMA)
        # IDs of the CSV given to this invocation; work and exports are limited to them, so one state
        # file can serve a 500-row demo and later the full corpus.
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS scope(review_id TEXT PRIMARY KEY)")
        self.lock = threading.RLock()

    # -- helpers -------------------------------------------------------------
    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def tx(self, fn):
        """Run fn(db) in one atomic transaction."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self.db)
                self.db.execute("COMMIT")
                return out
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    # -- reviews / records ---------------------------------------------------
    def review_count(self):
        return self.q("SELECT COUNT(*) FROM reviews")[0][0]

    def pending(self):
        """Nonempty reviews without a final record, in source order."""
        return self.q("""SELECT r.review_id, r.review_text FROM reviews r JOIN temp.scope USING(review_id)
                         LEFT JOIN records x ON x.review_id = r.review_id
                         WHERE x.status IS NULL ORDER BY r.row_idx""")

    def completed_ids(self):
        return [r[0] for r in self.q("""SELECT x.review_id FROM records x JOIN reviews r USING(review_id)
                                       JOIN temp.scope USING(review_id)
                                       WHERE x.status='completed' ORDER BY r.row_idx""")]

    def cache_get(self, key):
        row = self.q("SELECT label, origin_review_id, request_id FROM cache.results WHERE cache_key=?", (key,))
        return (json.loads(row[0][0]), row[0][1], row[0][2]) if row else None

    def log_call(self, db, call: dict):
        cols = ",".join(call)
        db.execute(f"INSERT INTO calls({cols}) VALUES({','.join('?' * len(call))})",
                   [json.dumps(v) if isinstance(v, (list, dict)) else v for v in call.values()])

    def log_call_now(self, call: dict):
        self.tx(lambda db: self.log_call(db, call))

    def spent(self, run_id=None):
        sql = "SELECT COALESCE(SUM(cost_usd),0) FROM calls" + (" WHERE run_id=?" if run_id else "")
        return self.q(sql, (run_id,) if run_id else ())[0][0]

    def start_run(self, run_id, command, input_path):
        self.tx(lambda db: db.execute("INSERT INTO runs(run_id,command,input_path,started_at) VALUES(?,?,?,?)",
                                      (run_id, command, str(input_path), time.time())))

    def end_run(self, run_id, wall_s, summary):
        self.tx(lambda db: db.execute("UPDATE runs SET ended_at=?, wall_s=?, summary=? WHERE run_id=?",
                                      (time.time(), wall_s, json.dumps(summary), run_id)))
