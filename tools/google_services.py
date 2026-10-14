"""Backward-compatibility shim.

The implementation moved to tools/google_auth.py, tools/gmail.py,
tools/calendar.py and tools/drive.py. Import from those modules directly;
this module re-exports everything so existing imports keep working.
"""
from tools.google_auth import *
from tools.gmail import *
from tools.calendar import *
from tools.drive import *
