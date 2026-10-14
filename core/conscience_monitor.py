# core/conscience_monitor.py
"""Mavis's conscience: the proactive inner voice.

Two loops:
- _tick (every 10 min): gathers real context (time, today's agenda, unread
  mail, today's memory notes, what she already said) and asks the brain for
  ONE timely proactive thought, or SILENCE. Nudges are topic-tagged and
  logged so she never nags about the same thing twice.
- _watch (every 5 min): cheap deterministic checks that don't need the LLM -
  currently "meeting starting within 15 minutes".
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.settings import BRAIN_DIR
from tools.calendar import get_today_calendar_events
from tools.gmail import get_unread_emails

MANILA = ZoneInfo("Asia/Manila")
# Two versions in one package: set MAVIS_SLIM_CONSCIENCE=1 to run conscience
# ticks as cheap toolless one-shot judgments instead of full tool-capable
# turns. Default off = original behavior.
SLIM_CONSCIENCE = os.environ.get("MAVIS_SLIM_CONSCIENCE", "") == "1"
LOG_FILE = os.path.join(BRAIN_DIR, "conscience_log.json")
TICK_SECONDS = 600
WATCH_SECONDS = 300
COOLDOWN_HOURS = 3
MEETING_WINDOW_MIN = 15


class ConscienceLog:
    """Persistent record of what the conscience already said, so she never
    nags about the same thing twice in a row."""

    def __init__(self, path=LOG_FILE):
        self.path = path
        self._lock = threading.Lock()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    def _write(self, entries):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries[-200:], f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def record(self, topic, message):
        with self._lock:
            entries = self._read()
            entries.append({
                "ts": datetime.now(MANILA).isoformat(),
                "topic": topic,
                "message": message[:300],
            })
            self._write(entries)

    def on_cooldown(self, topic, hours=COOLDOWN_HOURS):
        cutoff = datetime.now(MANILA) - timedelta(hours=hours)
        with self._lock:
            for e in self._read():
                try:
                    ts = datetime.fromisoformat(e["ts"])
                except Exception:
                    continue
                if e.get("topic") == topic and ts >= cutoff:
                    return True
        return False

    def recent_summary(self, hours=12):
        cutoff = datetime.now(MANILA) - timedelta(hours=hours)
        items = []
        with self._lock:
            for e in self._read():
                try:
                    ts = datetime.fromisoformat(e["ts"])
                except Exception:
                    continue
                if ts >= cutoff:
                    secs = (datetime.now(MANILA) - ts).total_seconds()
                    h, m = int(secs // 3600), int((secs % 3600) // 60)
                    when = f"{h}h{m}m ago" if h else f"{m}m ago"
                    items.append(
                        f"- {e.get('topic')} ({when}): {e.get('message', '')[:120]}")
        return "\n".join(items) if items else "(nothing recently)"


def _parse_agenda_line(line):
    """Parses '- <Title> at <HH:MM AM/PM>' (Asia/Manila) into a dict."""
    m = re.match(r"^-\s+(.+?)\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\s*$", line.strip())
    if not m:
        return None
    title, tstr = m.group(1), m.group(2)
    try:
        t = datetime.strptime(tstr.upper().replace(" ", ""), "%I:%M%p").time()
    except ValueError:
        return None
    dt = datetime.now(MANILA).replace(hour=t.hour, minute=t.minute,
                                      second=0, microsecond=0)
    return {"title": title, "start": dt}


def _upcoming_events(agenda_text, window_min=MEETING_WINDOW_MIN):
    now = datetime.now(MANILA)
    upcoming = []
    for line in (agenda_text or "").splitlines():
        ev = _parse_agenda_line(line)
        if not ev:
            continue
        delta_min = (ev["start"] - now).total_seconds() / 60
        if 0 <= delta_min <= window_min:
            upcoming.append(ev)
    return upcoming


class ConscienceManager:
    def __init__(self, voice, brain, alarms):
        self.voice = voice
        self.brain = brain
        self.alarms = alarms  # Reference to AlarmManager to check is_conversing
        self.log = ConscienceLog()

    def start_monitor(self):
        """Starts the conscience tick thread and the event-watch thread."""
        if SLIM_CONSCIENCE:
            print("[Conscience: slim mode - toolless one-shot ticks]")
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._watch_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # context gathering
    # ------------------------------------------------------------------
    def _today_memory_excerpt(self, chars=1500):
        path = os.path.join(BRAIN_DIR, "Ambient", "Daily",
                            datetime.now(MANILA).strftime("%Y-%m-%d") + ".md")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            return text[-chars:] if len(text) > chars else text
        except FileNotFoundError:
            return "(no memory notes today yet)"
        except Exception as e:
            return f"(unavailable: {e})"

    def _gather_context(self):
        now = datetime.now(MANILA)
        try:
            agenda = get_today_calendar_events()[:1500]
        except Exception as e:
            agenda = f"(unavailable: {e})"
        try:
            unread = get_unread_emails(max_results=5)[:1500]
        except Exception as e:
            unread = f"(unavailable: {e})"
        return {
            "time": now.strftime("%I:%M %p, %A"),
            "agenda": agenda,
            "unread": unread,
            "memory": self._today_memory_excerpt(),
            "recent_nudges": self.log.recent_summary(),
        }

    def _build_prompt(self, ctx):
        return (
            "System Command: You are Mavis's conscience - her proactive inner voice, "
            "not a chatbot. "
            f"It is {ctx['time']}. Silently consider everything below and decide "
            "whether Rey genuinely needs to hear something RIGHT NOW.\n\n"
            f"TODAY'S AGENDA:\n{ctx['agenda']}\n\n"
            f"UNREAD EMAIL:\n{ctx['unread']}\n\n"
            f"WHAT REY'S BEEN UP TO TODAY (memory notes):\n{ctx['memory']}\n\n"
            f"WHAT YOU ALREADY TOLD HIM (do not repeat these topics):\n"
            f"{ctx['recent_nudges']}\n\n"
            "Speak ONLY if there is a highly relevant, timely, proactive thought: "
            "a warning, a nudge toward his goals, or something he'd thank you for "
            "catching. Be specific - reference the actual event, email, or pattern. "
            "Never generic wellness filler.\n"
            "If everything is fine or nothing is timely, reply with exactly: SILENCE\n"
            "Otherwise reply with exactly this JSON and nothing else: "
            '{"topic": "<short-slug-like-this>", '
            '"message": "<one or two spoken sentences>"}'
        )

    @staticmethod
    def _parse_reply(reply):
        """Returns (topic, message), or (None, None) for SILENCE."""
        text = (reply or "").strip()
        if not text or "SILENCE" in text.upper():
            return None, None
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except (json.JSONDecodeError, AttributeError):
                data = None
            if isinstance(data, dict):
                topic = str(data.get("topic", "")).strip().lower()
                topic = topic.replace(" ", "-") or "general"
                message = str(data.get("message", "")).strip()
                return topic, message
        return "general", text

    # ------------------------------------------------------------------
    # speaking (with nag protection)
    # ------------------------------------------------------------------
    def _speak(self, topic, message):
        if self.log.on_cooldown(topic):
            print(f"\n[Conscience: '{topic}' on cooldown, staying silent.]")
            return None
        # Wait politely if the user started talking during processing.
        while self.alarms.is_conversing:
            time.sleep(2)
        self.voice.speak(message)
        self.log.record(topic, message)
        return message

    def _tick(self):
        """One silent evaluation. Returns the spoken text, or None if she stayed silent."""
        # Do not interrupt if Mavis is already talking or listening, and never run while
        # locked: process_input would answer "Access denied" and that would be spoken aloud.
        if self.alarms.is_conversing or not self.brain.is_authenticated:
            return None
        ctx = self._gather_context()
        try:
            prompt = self._build_prompt(ctx)
            reply = self.brain.think(prompt) if SLIM_CONSCIENCE \
                else self.brain.process_input(prompt)
        except Exception as e:
            print(f"\n[Conscience Engine Error: {e}]")
            return None
        topic, message = self._parse_reply(reply)
        if not message:
            return None
        return self._speak(topic, message)

    def _monitor_loop(self):
        """Silently evaluates the situation every 10 minutes."""
        while True:
            time.sleep(TICK_SECONDS)
            try:
                self._tick()
            except Exception as e:
                print(f"\n[Conscience Engine Error: {e}]")

    # ------------------------------------------------------------------
    # deterministic event watch (no LLM)
    # ------------------------------------------------------------------
    def _watch_once(self):
        """Checks for meetings starting soon. Returns titles announced."""
        if self.alarms.is_conversing or not self.brain.is_authenticated:
            return None
        try:
            agenda = get_today_calendar_events()
        except Exception as e:
            print(f"\n[Conscience watch error: {e}]")
            return None
        said = []
        for ev in _upcoming_events(agenda):
            key = hashlib.md5(
                f"{ev['title']}|{ev['start'].isoformat()}".encode()
            ).hexdigest()[:10]
            mins = int((ev["start"] - datetime.now(MANILA)).total_seconds() // 60)
            if self._speak(f"upcoming-{key}",
                           f"Heads up, Rey: '{ev['title']}' starts in {mins} minutes."):
                said.append(ev["title"])
        return said or None

    def _watch_loop(self):
        """Polls for time-sensitive events every 5 minutes."""
        while True:
            time.sleep(WATCH_SECONDS)
            try:
                self._watch_once()
            except Exception as e:
                print(f"\n[Conscience Engine Error: {e}]")
