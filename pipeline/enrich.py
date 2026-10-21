"""Stage 2: enrichment. Exact-text cache lookup (code) -> batches of <=50 distinct texts -> model ->
code validation -> one atomic save per response. Bounded retries; a single shared spend ledger."""
import hashlib
import json
import random
import signal
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .config import ModelConfig, call_cost
from .ledger import BudgetExceeded
from .llm import TransportError
from .prompts import ENRICH_INSTRUCTIONS, ENRICH_SCHEMA, enrich_payload
from .validate import MalformedResponse, validate_batch


def cache_key(text, cfg: ModelConfig):
    return hashlib.sha256(json.dumps([text, cfg.model, cfg.effort, cfg.label_config],
                                     ensure_ascii=False).encode()).hexdigest()


class RateLimiter:
    """Shared minimum spacing between request starts (requests/minute)."""
    def __init__(self, rpm=None):
        self.gap = 60.0 / rpm if rpm else 0.0
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait(self):
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_at)
            self.next_at = t + self.gap
        time.sleep(max(0.0, t - now))


class Enricher:
    def __init__(self, store, client, cfg: ModelConfig, ledger, run_id, workers=1, rpm=None,
                 log=print, stop_after_batches=None, backoff_base=1.0, rates_model=None):
        self.store, self.client, self.cfg, self.ledger = store, client, cfg, ledger
        self.run_id, self.workers, self.log = run_id, max(1, workers), log
        self.limiter = RateLimiter(rpm)
        self.stop = threading.Event()
        self.stop_reason = ""
        self.stop_after_batches = stop_after_batches
        self.backoff_base = backoff_base
        self.rates_model = rates_model or cfg.model
        self.stats = {"calls": 0, "failed_calls": 0, "completed": 0, "cache_hits": 0, "quarantined": 0,
                      "transport_unresolved": 0, "batches_done": 0}
        self.slock = threading.Lock()
        self.consecutive_transport_failures = 0
        prior = store.q("""SELECT COUNT(*) FROM records WHERE status='completed'""")[0][0]
        self.phase = "resume" if prior else "initial"

    # -- bookkeeping ---------------------------------------------------------
    def bump(self, k, n=1):
        with self.slock:
            self.stats[k] += n

    def reserve_for(self, payload, n):
        est_in = int((len(ENRICH_INSTRUCTIONS) + len(payload)) / 2.0) + 50   # conservative chars->tokens
        return self.ledger.reserve(call_cost(self.rates_model, est_in, self.cfg.output_cap(n)))

    # -- cache pass (code only, no calls) -------------------------------------
    def resolve_from_cache(self, pending):
        groups = {}
        for rid, text in pending:
            if text.strip():
                groups.setdefault(cache_key(text, self.cfg), []).append((rid, text))
        in_input = {r[0] for r in self.store.q("SELECT review_id FROM temp.scope")}
        todo, rows = [], []
        for key, members in groups.items():
            hit = self.store.cache_get(key)
            if not hit:
                todo.append((key, members))
                continue
            _, origin, _ = hit
            for rid, _ in members:
                src = origin if (origin != rid and origin in in_input) else None
                rows.append((rid, "completed", None, key, src, self.cfg.label_config, 0, self.run_id, time.time()))
        if rows:
            self.store.tx(lambda db: db.executemany("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)", rows))
            self.bump("cache_hits", len(rows)); self.bump("completed", len(rows))
        return todo

    # -- one model call with bounded transport retries -----------------------
    def call(self, members, error_note, attempt_round, reservation_hint=None):
        texts = [m[0][1] for m in members]
        payload = enrich_payload(texts, error_note)
        ids = [m[0][0] for m in members]
        cap = self.cfg.output_cap(len(texts))
        for attempt in range(1, self.cfg.max_transport_retries + 2):
            res = reservation_hint if (reservation_hint and attempt == 1) else self.reserve_for(payload, len(texts))
            reservation_hint = None
            self.limiter.wait()
            t0, started = time.monotonic(), time.time()
            base = {"run_id": self.run_id, "role": "enrich", "phase": self.phase, "review_ids": ids,
                    "model": self.cfg.model, "effort": self.cfg.effort, "label_config": self.cfg.label_config,
                    "attempt": attempt_round * 10 + attempt, "max_output_tokens": cap, "started_at": started}
            try:
                resp = self.client.respond(ENRICH_INSTRUCTIONS, payload, ENRICH_SCHEMA, "labels", cap)
            except TransportError as e:
                self.ledger.settle(res, None if e.unknown_charge else 0.0)
                self.store.log_call_now({**base, "request_id": "failed-" + uuid.uuid4().hex[:16], "outcome": "failed",
                                         "error": str(e)[:300], "input_tokens": 0, "output_tokens": 0,
                                         "cached_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0,
                                         "latency_s": time.monotonic() - t0, "unknown_charge": int(e.unknown_charge)})
                self.bump("failed_calls")
                if not e.retryable or attempt > self.cfg.max_transport_retries:
                    raise
                delay = e.retry_after or self.backoff_base * (2 ** (attempt - 1))
                time.sleep(delay + random.uniform(0, delay / 2))
                continue
            cost = call_cost(self.rates_model, resp.input_tokens, resp.output_tokens, resp.cached_tokens)
            self.ledger.settle(res, cost)
            self.bump("calls")
            call = {**base, "request_id": resp.request_id, "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens, "cached_tokens": resp.cached_tokens,
                    "reasoning_tokens": resp.reasoning_tokens, "cost_usd": cost,
                    "latency_s": time.monotonic() - t0, "ratelimit": resp.ratelimit or None}
            return resp, call
        raise AssertionError("unreachable")

    # -- one batch: call, validate, save atomically, retry failures once -----
    def process(self, members, reservation):
        todo, note, rnd = members, None, 0
        while todo:
            resp, call = self.call(todo, note, rnd, reservation)
            reservation = None
            texts = [m[0][1] for m in todo]
            try:
                if resp.status != "completed":
                    raise MalformedResponse(f"incomplete:{resp.incomplete_reason or 'unknown'}")
                good, bad, notes = validate_batch(resp.text, texts)
                err = None
            except MalformedResponse as e:
                good, bad, notes, err = {}, {str(i + 1): "malformed_response" for i in range(len(todo))}, [], str(e)
            call["outcome"] = "succeeded" if good else "failed"
            call["error"] = "; ".join(filter(None, [err] + notes + [f"{todo[int(k)-1][0][0]}:{v}" for k, v in bad.items()]))[:500] or None
            final_bad = bad if rnd >= 1 else {}
            self.save(call, todo, good, final_bad, rnd + 1)
            if not good:
                self.bump("failed_calls")
            if not bad or rnd >= 1:
                return
            retry = [todo[int(k) - 1] for k in sorted(bad, key=int)]
            note = (f"Your previous output was rejected ({err}). Return valid JSON matching the schema."
                    if err else "Previous answers for these reviews failed validation: " +
                    "; ".join(f"id {i + 1}: {bad[k]}" for i, k in enumerate(sorted(bad, key=int))) +
                    ". Evidence quotes must be exact substrings.")
            todo, rnd = retry, rnd + 1
            if len(todo) > 1 and err:
                # whole response broke: retry in halves so one bad item can't sink everything
                half = (len(todo) + 1) // 2
                self.process_retry_halves(todo[:half], note); self.process_retry_halves(todo[half:], note)
                return

    def process_retry_halves(self, todo, note):
        resp, call = self.call(todo, note, 1)
        texts = [m[0][1] for m in todo]
        try:
            if resp.status != "completed":
                raise MalformedResponse(f"incomplete:{resp.incomplete_reason or 'unknown'}")
            good, bad, notes = validate_batch(resp.text, texts)
            err = None
        except MalformedResponse as e:
            good, bad, notes, err = {}, {str(i + 1): "malformed_response" for i in range(len(todo))}, [], str(e)
        call["outcome"] = "succeeded" if good else "failed"
        call["error"] = "; ".join(filter(None, [err] + notes))[:500] or None
        self.save(call, todo, good, bad, 2)

    def save(self, call, todo, good, final_bad, attempts):
        now = time.time()
        cache_rows, rec_rows = [], []
        for lid, label in good.items():
            key, group = todo[int(lid) - 1][1], todo[int(lid) - 1][0][2]
            origin = group[0][0]
            cache_rows.append((key, self.cfg.label_config, json.dumps(label, ensure_ascii=False), origin,
                               call["request_id"], now))
            for i, (rid, _) in enumerate(group):
                rec_rows.append((rid, "completed", None, key, None if i == 0 else origin,
                                 self.cfg.label_config, attempts, self.run_id, now))
        q_rows = []
        for lid, reason in final_bad.items():
            group = todo[int(lid) - 1][0][2]
            for i, (rid, _) in enumerate(group):
                q_rows.append((rid, "quarantined", f"validation_failed:{reason}" if i == 0 else
                               f"same_text_as_quarantined:{group[0][0]}", None, None, self.cfg.label_config,
                               attempts, self.run_id, now))

        def fn(db):
            self.store.log_call(db, call)
            db.executemany("INSERT OR REPLACE INTO cache.results VALUES(?,?,?,?,?,?)", cache_rows)
            db.executemany("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)", rec_rows + q_rows)
        self.store.tx(fn)
        self.bump("completed", len(rec_rows)); self.bump("quarantined", len(q_rows))

    # -- driver --------------------------------------------------------------
    def run(self):
        todo = self.resolve_from_cache(self.store.pending())
        # members: ((first_rid, text, group), key); one representative per distinct text
        reps = [((g[0][0], g[0][1], g), key) for key, g in todo]
        batches = [reps[i:i + self.cfg.max_batch] for i in range(0, len(reps), self.cfg.max_batch)]
        self.log(f"[enrich] phase={self.phase} distinct_texts_to_send={len(reps)} batches={len(batches)} "
                 f"cache_hits={self.stats['cache_hits']} workers={self.workers}")
        old = signal.getsignal(signal.SIGINT)
        if threading.current_thread() is threading.main_thread():
            def on_sigint(*_):
                if self.stop.is_set():
                    raise KeyboardInterrupt
                self.stop_reason = "interrupted (Ctrl-C): finishing in-flight batches, then saving"
                self.log(f"\n[enrich] {self.stop_reason}"); self.stop.set()
            signal.signal(signal.SIGINT, on_sigint)
        t0 = time.monotonic()
        try:
            with ThreadPoolExecutor(self.workers) as pool:
                inflight, it = set(), iter(batches)
                admitted = 0
                while True:
                    while not self.stop.is_set() and len(inflight) < self.workers:
                        if self.stop_after_batches is not None and admitted >= self.stop_after_batches:
                            self.stop_reason = f"stop_after_batches={self.stop_after_batches}"; self.stop.set(); break
                        batch = next(it, None)
                        if batch is None:
                            break
                        try:
                            res = self.reserve_for(enrich_payload([m[0][1] for m in batch]), len(batch))
                        except BudgetExceeded as e:
                            self.stop_reason = f"budget: {e}"; self.log(f"[enrich] stop admitting: {e}")
                            self.stop.set(); break
                        inflight.add(pool.submit(self.process, batch, res)); admitted += 1
                    if not inflight:
                        break
                    done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                    for f in done:
                        try:
                            f.result()
                            self.consecutive_transport_failures = 0
                        except TransportError as e:
                            self.consecutive_transport_failures += 1
                            self.bump("transport_unresolved")
                            self.log(f"[enrich] batch left pending after retries: {e}")
                            if self.consecutive_transport_failures >= 3 or getattr(e, "status", None) == 429:
                                self.stop_reason = f"halting: transport/throttle failures ({e})"; self.stop.set()
                        except BudgetExceeded as e:
                            self.stop_reason = f"budget during retry: {e}"; self.stop.set()
                        self.bump("batches_done")
                        el = time.monotonic() - t0
                        self.log(f"[enrich] batches {self.stats['batches_done']}/{len(batches)} "
                                 f"completed={self.stats['completed']} quarantined={self.stats['quarantined']} "
                                 f"calls={self.stats['calls']} spent=${self.ledger.snapshot()['spent']:.4f} "
                                 f"elapsed={el:.1f}s")
        finally:
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, old)
        self.stats["wall_s"] = round(time.monotonic() - t0, 3)
        self.stats["stopped"] = self.stop_reason
        self.stats["phase"] = self.phase
        return self.stats
