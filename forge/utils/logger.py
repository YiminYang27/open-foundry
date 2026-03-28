"""Logging helpers and color constants for the open-foundry orchestrator."""

import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Color constants
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


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class Logger:
    """Session-aware logger that writes to both stdout and a session log file."""

    def __init__(self) -> None:
        self._session_log: Path | None = None

    def set_session_log(self, path: Path | None) -> None:
        """Set (or clear) the file path used for session-level logging."""
        self._session_log = path

    def _log_to_file(self, plain_msg: str) -> None:
        if self._session_log is not None:
            with open(self._session_log, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M:%S')} {plain_msg}\n")

    def info(self, msg):
        print(f"{BLUE}[INFO]{NC} {msg}")
        self._log_to_file(f"[INFO] {msg}")

    def ok(self, msg):
        print(f"{GREEN}[OK]{NC} {msg}")
        self._log_to_file(f"[OK] {msg}")

    def warn(self, msg):
        print(f"{YELLOW}[WARN]{NC} {msg}")
        self._log_to_file(f"[WARN] {msg}")

    def err(self, msg):
        print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)
        self._log_to_file(f"[ERROR] {msg}")

    def fatal(self, msg):
        self.err(msg)
        sys.exit(1)

    def speaker_line(self, name, text):
        print(f"{CYAN}[{name}]{NC} {text}")
        self._log_to_file(f"[{name}] {text}")


logger = Logger()
