# core/ambient_router.py
"""Decides whether a transcribed utterance is a command for Mavis or background chatter."""
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import List, NamedTuple, Tuple

from core.auth import scrub_passwords

WAKE_WORD = "mavis"
# Google STT often mishears short names, so accept common variants plus a close fuzzy match.
_ALIASES = {"mavis", "mavees", "mavers", "mavus", "mavies", "maves", "mavice", "mavs"}
_FUZZY_THRESHOLD = 0.85  # "davis" scores 0.80 and must not wake her
_FILLER = {"hey", "hi", "hello", "ok", "okay"}
_WORD = re.compile(r"[A-Za-z']+")


def _is_wake_token(token: str) -> bool:
    token = token.lower().split("'")[0]
    if token in _ALIASES:
        return True
    # Same first letter: substring-style near misses like "avis" (the rental company) must not wake her.
    return (len(token) >= 4 and token[0] == WAKE_WORD[0]
            and SequenceMatcher(None, token, WAKE_WORD).ratio() >= _FUZZY_THRESHOLD)


def is_wake_word(text: str) -> bool:
    return any(_is_wake_token(m.group()) for m in _WORD.finditer(text or ""))


def strip_wake(text: str) -> str:
    """Remove the wake word (and a directly preceding 'hey'/'okay') and tidy the rest."""
    text = text or ""
    for m in _WORD.finditer(text):
        if not _is_wake_token(m.group()):
            continue
        start, end = m.start(), m.end()
        before = text[:start]
        filler = re.search(r"(?:^|\s)(" + "|".join(_FILLER) + r")[\s,]*$", before, re.IGNORECASE)
        if filler:
            before = before[:filler.start(1)]
        remainder = (before + " " + text[end:]).strip()
        remainder = re.sub(r"\s+", " ", remainder)
        return remainder.strip(" \t,.:;!?-")
    return text.strip()


class Route(NamedTuple):
    kind: str  # "command" | "wake_only" | "background" | "ignored"
    text: str


class BackgroundBuffer:
    """Thread-safe holding area for background chatter between batch flushes."""

    def __init__(self, clock=datetime.now):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: List[Tuple[datetime, str]] = []

    def add(self, text: str) -> bool:
        cleaned = scrub_passwords(text or "")
        if not cleaned:
            return False
        with self._lock:
            self._entries.append((self._clock(), cleaned))
        return True

    def drain(self) -> List[Tuple[datetime, str]]:
        with self._lock:
            entries, self._entries = self._entries, []
        return entries

    def restore(self, entries: List[Tuple[datetime, str]]) -> None:
        with self._lock:
            self._entries = list(entries) + self._entries

    def word_count(self) -> int:
        with self._lock:
            return sum(len(t.split()) for _, t in self._entries)


class AmbientRouter:
    def __init__(self, followup_seconds: float = 8.0, clock=time.monotonic):
        self._followup_seconds = followup_seconds
        self._clock = clock
        self._followup_until = 0.0
        self._paused = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def open_followup(self) -> None:
        """Treat the next utterance as a command without the wake word (used after she replies)."""
        self._followup_until = self._clock() + self._followup_seconds

    def route(self, text: str) -> Route:
        text = (text or "").strip()
        if not text:
            return Route("ignored", "")
        if is_wake_word(text):
            command = strip_wake(text)
            if command:
                self._followup_until = 0.0
                return Route("command", command)
            self._followup_until = self._clock() + self._followup_seconds
            return Route("wake_only", "")
        if self._clock() < self._followup_until:
            self._followup_until = 0.0
            return Route("command", text)
        if self._paused:
            return Route("ignored", text)
        return Route("background", text)
