"""Central settings for Mavis. All paths in one place.

Environment variables override the defaults, so the code no longer carries
hardcoded Windows usernames:

  MAVIS_DOWNLOADS_DIR  - sandbox for local file tools (default: ~/Download)
  MAVIS_BRAIN_DIR      - alarms + Obsidian memory vault (default: <downloads>/Brain)
  MAVIS_ALARM_FILE     - alarm store (default: <brain>/alarms.json)
  MAVIS_MEMORY_FILE    - long-term memory note (default: <brain>/Mavis_Memory.md)
"""
import os


def _default_downloads_dir():
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "Download")


DOWNLOADS_DIR = os.environ.get("MAVIS_DOWNLOADS_DIR", _default_downloads_dir())
BRAIN_DIR = os.environ.get("MAVIS_BRAIN_DIR",
                           os.path.join(DOWNLOADS_DIR, "Brain"))
ALARM_FILE = os.environ.get("MAVIS_ALARM_FILE",
                            os.path.join(BRAIN_DIR, "alarms.json"))
MEMORY_FILE = os.environ.get("MAVIS_MEMORY_FILE",
                             os.path.join(BRAIN_DIR, "Mavis_Memory.md"))


def ensure_brain_dir():
    os.makedirs(BRAIN_DIR, exist_ok=True)
