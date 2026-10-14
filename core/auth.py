# core/auth.py
"""Spoken-password helpers shared by the brain and the ambient listener.

Matching is whole-word, so "similar" or "hilarious" never contains the password
"ila". The same patterns are used to scrub the words out of anything that is
saved to the background buffer, the vault, or sent to Gemini.
"""
import re

VALID_PASSWORDS = [
    "aila", "ai'la", "ayla", "isla", "eila", "ila", "eyla",
    "ay la", "ai la", "jelly", "je ly",
]


def _fix_quotes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def _compile(password: str) -> "re.Pattern":
    body = re.escape(password).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![\w'])" + body + r"(?![\w'])", re.IGNORECASE)


_PATTERNS = [_compile(p) for p in VALID_PASSWORDS]


def contains_password(text: str) -> bool:
    fixed = _fix_quotes(text or "")
    return any(p.search(fixed) for p in _PATTERNS)


def scrub_passwords(text: str) -> str:
    cleaned = _fix_quotes(text or "")
    for pattern in _PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
