# core/memory_graph.py
"""Writes ambient conversation into the Obsidian vault as a linked graph.

Layout under the vault (default: the same Brain folder Mavis_Memory.md lives in):
    Mavis_Memory.md            hub; gets one [[daily]] link per day
    Ambient/Daily/<date>.md    one note per day, links the hub and every batch
    Ambient/Batches/batch-*.md raw batch (status: pending -> processed), linked to its day and previous batch
    Ambient/Notes/<kind>-<slug>.md  people / topic notes extracted by Gemini, linked back to batches
"""
import os
import re
from datetime import datetime
from typing import List, NamedTuple, Tuple

from core.settings import BRAIN_DIR

DEFAULT_VAULT = os.environ.get("MAVIS_VAULT", BRAIN_DIR)
HUB_NAME = "Mavis_Memory"
PURGED_MARKER = "_raw transcript purged_"

_RAW_SECTION = re.compile(r"(## Raw\n)(.*?)(\n## |\Z)", re.DOTALL)
_EXTRACTED_SECTION = re.compile(r"## Extracted\n(.*?)(?=\n## |\Z)", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


class BatchRef(NamedTuple):
    name: str
    path: str


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "untitled"


def _status(text: str) -> str:
    m = re.search(r"^status:\s*(\w+)", text, re.MULTILINE)
    return m.group(1) if m else ""


def _date(text: str) -> str:
    m = re.search(r"^date:\s*(\S+)", text, re.MULTILINE)
    return m.group(1) if m else ""


class MemoryGraph:
    def __init__(self, vault_path: str = None, clock=datetime.now):
        self.vault = vault_path or DEFAULT_VAULT
        self._clock = clock
        self._batches = os.path.join(self.vault, "Ambient", "Batches")
        self._daily = os.path.join(self.vault, "Ambient", "Daily")
        self._notes = os.path.join(self.vault, "Ambient", "Notes")

    # ---- small file helpers -------------------------------------------------
    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _write(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def _append(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    def _batch_path(self, name: str) -> str:
        return os.path.join(self._batches, f"{name}.md")

    def _batch_names(self) -> List[str]:
        if not os.path.isdir(self._batches):
            return []
        return sorted(f[:-3] for f in os.listdir(self._batches) if f.endswith(".md"))

    # ---- writing ------------------------------------------------------------
    def write_batch(self, entries: List[Tuple[datetime, str]]) -> BatchRef:
        now = self._clock()
        base = f"batch-{now:%Y%m%d-%H%M}"
        name, n = base, 2
        while os.path.exists(self._batch_path(name)):
            name = f"{base}-{n}"
            n += 1
        names = self._batch_names()
        prev = names[-1] if names else None
        day = f"{entries[0][0]:%Y-%m-%d}" if entries else f"{now:%Y-%m-%d}"

        header = f"Day: [[{day}]]" + (f" \u00b7 Previous: [[{prev}]]" if prev else "")
        lines = ["---", "type: ambient-batch", "status: pending", f"date: {day}", "---",
                 f"# {name}", "", header, "", "## Raw"]
        for ts, text in entries:
            lines.append(f"- {ts:%H:%M} {' '.join(str(text).split())}")
        path = self._batch_path(name)
        self._write(path, "\n".join(lines) + "\n")

        self._append_daily(day, f"- [[{name}]]")
        self._ensure_hub_link(day)
        return BatchRef(name, path)

    def _append_daily(self, day: str, line: str) -> None:
        path = os.path.join(self._daily, f"{day}.md")
        if not os.path.exists(path):
            self._write(path, f"# {day}\n\nHub: [[{HUB_NAME}]]\n\n")
        self._append(path, line + "\n")

    def _ensure_hub_link(self, day: str) -> None:
        hub = os.path.join(self.vault, f"{HUB_NAME}.md")
        existing = self._read(hub) if os.path.exists(hub) else ""
        if f"[[{day}]]" not in existing:
            self._append(hub, f"\n- [[{day}]] (ambient notes)")

    def _touch_note(self, kind: str, title: str, batch: str, day: str) -> str:
        slug = f"{kind}-{_slug(title)}"
        path = os.path.join(self._notes, f"{slug}.md")
        mention = f"- [[{batch}]] ({day})"
        if not os.path.exists(path):
            self._write(path, f"---\ntype: {kind}\n---\n# {title}\n\n## Mentions\n{mention}\n")
        elif f"[[{batch}]]" not in self._read(path):
            self._append(path, mention + "\n")
        return slug

    def apply_extraction(self, ref: BatchRef, data: dict) -> None:
        text = self._read(ref.path)
        if _status(text) != "pending":
            return  # already processed: nothing to duplicate
        day = _date(text)

        people = [self._touch_note("person", p, ref.name, day) for p in data.get("people", []) if p]
        topics = [self._touch_note("topic", t, ref.name, day) for t in data.get("topics", []) if t]
        actions = []
        for item in data.get("action_items", []):
            action = item.get("text") if isinstance(item, dict) else item
            if action:
                actions.append(str(action))
                self._append_daily(day, f"- [ ] {action} (from [[{ref.name}]])")

        out = ["", "## Extracted", f"Summary: {data.get('summary', '').strip()}", ""]
        if people:
            out.append("People: " + ", ".join(f"[[{s}]]" for s in people))
        if topics:
            out.append("Topics: " + ", ".join(f"[[{s}]]" for s in topics))
        if actions:
            out += ["", "Actions:"] + [f"- [ ] {a}" for a in actions]
        text = text.replace("status: pending", "status: processed", 1).rstrip("\n")
        self._write(ref.path, text + "\n" + "\n".join(out) + "\n")
        self._link_related(people + topics)

    def mark_failed(self, ref: BatchRef) -> None:
        """Stop retrying a batch Gemini could not evaluate. Its raw text is still purged on schedule."""
        text = self._read(ref.path)
        if _status(text) != "pending":
            return
        text = text.replace("status: pending", "status: failed", 1).rstrip("\n")
        self._write(ref.path, text + "\n\n_Gemini evaluation failed after repeated attempts._\n")

    # ---- explicit memories --------------------------------------------------
    def absorb_explicit_memory(self, memory_text: str, timestamp: str = None) -> list:
        """Links an explicitly saved memory into the knowledge graph.

        Finds [[person-...]] / [[topic-...]] wikilinks in the text, ensures
        each note exists, and records the memory under its ## Memories
        section. Returns the slugs that were linked.
        """
        ts = timestamp or self._clock().strftime("%Y-%m-%d %H:%M")
        linked = []
        for slug in dict.fromkeys(_WIKILINK.findall(memory_text)):
            slug = slug.strip().lower()
            if not slug or "/" in slug or "\\" in slug or slug.startswith("batch-"):
                continue
            kind, _, rest = slug.partition("-")
            if kind not in ("person", "topic") or not rest:
                kind, title = "topic", slug
            else:
                title = rest.replace("-", " ")
            path = os.path.join(self._notes, f"{slug}.md")
            entry = f"- [{ts}] {memory_text.strip()}"
            if not os.path.exists(path):
                self._write(path,
                            f"---\ntype: {kind}\n---\n# {title}\n\n"
                            f"## Memories\n{entry}\n")
            else:
                text = self._read(path)
                if "## Memories" not in text:
                    text = text.rstrip("\n") + "\n\n## Memories\n"
                if entry not in text:
                    text = text.rstrip("\n") + "\n" + entry + "\n"
                self._write(path, text)
            linked.append(slug)
        return linked

    def _link_related(self, slugs: list) -> None:
        """Adds co-occurrence edges between notes mentioned in the same batch,
        so the Obsidian graph shows relationships, not just mentions."""
        for i, a in enumerate(slugs):
            for b in slugs[i + 1:]:
                for src, dst in ((a, b), (b, a)):
                    path = os.path.join(self._notes, f"{src}.md")
                    if not os.path.exists(path):
                        continue
                    text = self._read(path)
                    if f"[[{dst}]]" in text:
                        continue
                    if "## Related" not in text:
                        text = text.rstrip("\n") + "\n\n## Related\n"
                    text = text.rstrip("\n") + f"\n- [[{dst}]] (mentioned together)\n"
                    self._write(path, text)

    # ---- reading ------------------------------------------------------------
    def pending_batches(self) -> List[BatchRef]:
        refs = []
        for name in self._batch_names():
            path = self._batch_path(name)
            if _status(self._read(path)) == "pending":
                refs.append(BatchRef(name, path))
        return refs

    def read_batch_entries(self, ref: BatchRef) -> List[Tuple[datetime, str]]:
        text = self._read(ref.path)
        day = _date(text)
        m = _RAW_SECTION.search(text)
        entries = []
        for line in (m.group(2) if m else "").splitlines():
            parsed = re.match(r"^- (\d\d):(\d\d) (.*)$", line)
            if parsed:
                hh, mm, body = parsed.groups()
                entries.append((datetime.strptime(f"{day} {hh}:{mm}", "%Y-%m-%d %H:%M"), body))
        return entries

    def recent_context(self, ref: BatchRef, max_chars: int = 2000) -> str:
        """The previous batch's extraction (if processed) plus how often its people/topics recur."""
        m = re.search(r"Previous: \[\[([^\]]+)\]\]", self._read(ref.path))
        if not m:
            return ""
        prev_path = self._batch_path(m.group(1))
        if not os.path.exists(prev_path):
            return ""
        prev_text = self._read(prev_path)
        if _status(prev_text) != "processed":
            return ""
        section = _EXTRACTED_SECTION.search(prev_text)
        if not section:
            return ""
        context = section.group(1).strip()
        recurring = []
        for link in dict.fromkeys(_WIKILINK.findall(context)):
            note = os.path.join(self._notes, f"{link}.md")
            if os.path.exists(note):
                count = self._read(note).count("[[batch-")
                recurring.append(f"{link}: mentioned in {count} batch(es)")
        if recurring:
            context += "\n\nRecurring: " + "; ".join(recurring)
        return context[:max_chars]

    # ---- retention ----------------------------------------------------------
    def purge_raw(self, days: int = 7) -> int:
        """Redact the raw transcript of processed/failed batches older than `days`; keep links and extraction."""
        today = self._clock().date()
        purged = 0
        for name in self._batch_names():
            path = self._batch_path(name)
            text = self._read(path)
            if _status(text) not in ("processed", "failed"):
                continue
            try:
                age = (today - datetime.strptime(_date(text), "%Y-%m-%d").date()).days
            except ValueError:
                continue
            if age <= days:
                continue
            match = _RAW_SECTION.search(text)
            if not match or match.group(2).strip() == PURGED_MARKER:
                continue
            new_text = text[:match.start(2)] + PURGED_MARKER + "\n" + text[match.end(2):]
            self._write(path, new_text)
            purged += 1
        return purged
