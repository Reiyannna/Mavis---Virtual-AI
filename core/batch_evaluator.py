# core/batch_evaluator.py
"""Flushes the background buffer into the vault, then asks Gemini to extract what matters.

Order matters: the raw batch is written to the vault BEFORE Gemini is called, so a
rate limit or network failure never loses text. Failed batches stay `pending` and are
retried with a backoff.
"""
import json
import re
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional, Tuple

Entries = List[Tuple[datetime, str]]


def build_prompt(entries: Entries, context: str = "") -> str:
    transcript = "\n".join(f"[{ts:%H:%M}] {text}" for ts, text in entries)
    parts = [
        "You are silently reviewing background audio that was transcribed near the user. "
        "It may include other people talking and speech-recognition errors. "
        "Ignore small talk. Extract only things worth remembering.",
        "Reply with ONLY a JSON object, no markdown, with exactly these keys: "
        '"summary" (one or two sentences), "action_items" (list of short strings: tasks, '
        'deadlines or commitments), "people" (list of names), "topics" (list of short topic names). '
        "Use empty lists when there is nothing.",
    ]
    if context:
        parts.append("Context from the previous batch:\n" + context)
    parts.append("Transcript:\n" + transcript)
    return "\n\n".join(parts)


def parse_extraction(raw) -> Optional[dict]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        return None

    def _list(key):
        value = data.get(key, [])
        return [v for v in value if isinstance(v, (str, dict))] if isinstance(value, list) else []

    return {
        "summary": data["summary"],
        "action_items": _list("action_items"),
        "people": [p for p in _list("people") if isinstance(p, str)],
        "topics": [t for t in _list("topics") if isinstance(t, str)],
    }


class BatchEvaluator:
    def __init__(self, graph, buffer, generate_fn: Callable[[str], str], min_words: int = 40,
                 interval: float = 300.0, retry_backoff: float = 60.0, purge_days: int = 7,
                 max_attempts: int = 5, clock=time.monotonic):
        self._graph = graph
        self._buffer = buffer
        self._generate = generate_fn
        self._min_words = min_words
        self._interval = interval
        self._backoff = retry_backoff
        self._purge_days = purge_days
        self._max_attempts = max_attempts
        self._attempts = {}
        self._clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._next_retry = 0.0
        self._last_purge = None

    def _fail(self, ref) -> bool:
        """Back off, and give up on a batch that keeps failing so it cannot block the queue."""
        self._next_retry = self._clock() + self._backoff
        attempts = self._attempts.get(ref.name, 0) + 1
        self._attempts[ref.name] = attempts
        if attempts >= self._max_attempts:
            self._graph.mark_failed(ref)
            self._attempts.pop(ref.name, None)
            print(f"\n[Ambient: giving up on {ref.name} after {attempts} attempts.]")
        return False

    def _evaluate(self, ref) -> bool:
        entries = self._graph.read_batch_entries(ref)
        if not entries:
            self._graph.apply_extraction(ref, {"summary": "(empty batch)"})
            return True
        try:
            raw = self._generate(build_prompt(entries, self._graph.recent_context(ref)))
        except Exception as e:
            print(f"\n[Ambient: Gemini evaluation failed, will retry: {e}]")
            return self._fail(ref)
        data = parse_extraction(raw)
        if data is None:
            print("\n[Ambient: Gemini returned unusable output, will retry.]")
            return self._fail(ref)
        self._graph.apply_extraction(ref, data)
        return True

    def flush_once(self) -> str:
        with self._lock:
            entries = self._buffer.drain()
            if not entries:
                return "skipped-empty"
            if sum(len(text.split()) for _, text in entries) < self._min_words:
                self._buffer.restore(entries)
                return "skipped-short"
            ref = self._graph.write_batch(entries)
            if self._clock() < self._next_retry:
                return "queued-retry"
            return "evaluated" if self._evaluate(ref) else "queued-retry"

    def retry_pending(self) -> int:
        with self._lock:
            if self._clock() < self._next_retry:
                return 0
            done = 0
            for ref in self._graph.pending_batches()[:2]:
                if not self._evaluate(ref):
                    break
                done += 1
            return done

    def _loop(self):
        while not self._stop.wait(self._interval):
            try:
                self.flush_once()
                self.retry_pending()
                now = self._clock()
                if self._last_purge is None or now - self._last_purge >= 86400:
                    self._graph.purge_raw(self._purge_days)
                    self._last_purge = now
            except Exception as e:
                print(f"\n[Ambient: batch loop error: {e}]")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
