"""Logging helpers and color constants for the open-foundry orchestrator."""

import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

if sys.stdout.isatty():
    RED    = '\033[0;31m'
    GREEN  = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE   = '\033[0;34m'
    CYAN   = '\033[0;36m'
    BOLD   = '\033[1m'
    NC     = '\033[0m'
else:
    RED = GREEN = YELLOW = BLUE = CYAN = BOLD = NC = ''


_session_log: Path | None = None


def set_session_log(path: Path | None) -> None:
    """Set (or clear) the file path used for session-level logging."""
    global _session_log
    _session_log = path


def _log_to_file(plain_msg: str) -> None:
    if _session_log is not None:
        with open(_session_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} {plain_msg}\n")


def info(msg):  print(f"{BLUE}[INFO]{NC} {msg}"); _log_to_file(f"[INFO] {msg}")
def ok(msg):    print(f"{GREEN}[OK]{NC} {msg}"); _log_to_file(f"[OK] {msg}")
def warn(msg):  print(f"{YELLOW}[WARN]{NC} {msg}"); _log_to_file(f"[WARN] {msg}")
def err(msg):   print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr); _log_to_file(f"[ERROR] {msg}")
def fatal(msg): err(msg); sys.exit(1)


def speaker_line(name, text):
    print(f"{CYAN}[{name}]{NC} {text}"); _log_to_file(f"[{name}] {text}")
