"""LLM provider abstraction for the open-foundry orchestrator.

Defines LLMProvider Protocol (only complete() is required) and
ClaudeCLI implementation that wraps `claude -p` subprocess calls.
"""

import subprocess
import time
from typing import Protocol

from forge.utils.logger import logger


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """Provider-agnostic interface for LLM calls.
    Only complete() is required. stream() is optional (used by synthesize()).
    """

    def complete(self, prompt: str, *,
                 label: str = "",
                 timeout: int = 600,
                 max_retries: int = 3) -> str:
        """Send prompt, return response text. Empty string on failure."""
        ...


# ---------------------------------------------------------------------------
# Claude CLI implementation
# ---------------------------------------------------------------------------

class ClaudeCLI:
    """LLM provider wrapping the ``claude -p`` CLI."""

    def __init__(self, model: str, skip_perms: bool = True,
                 dry_run: bool = False) -> None:
        self._model = model
        self._skip_perms = skip_perms
        self._dry_run = dry_run

    @property
    def model(self) -> str:
        return self._model

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def complete(self, prompt: str, *,
                 label: str = "",
                 timeout: int = 600,
                 max_retries: int = 3) -> str:
        """Send prompt to Claude CLI and return response text.

        timeout=600: agents with WebSearch/file access need up to 10 min.
        Orchestrator calls should override with timeout=120.
        """
        if self._dry_run:
            logger.info(f"[DRY RUN] {label} prompt ({len(prompt)} chars)")
            return ""

        # Pass prompt via stdin to avoid OS ARG_MAX limit on long prompts
        cmd = ['claude', '-p', '-', '--model', self._model]
        if self._skip_perms:
            cmd.append('--dangerously-skip-permissions')

        for attempt in range(max_retries):
            try:
                # start_new_session isolates child from parent's process group
                # so Ctrl+\ (SIGQUIT) only reaches forge.py, not the subprocess.
                result = subprocess.run(cmd, input=prompt, capture_output=True,
                                        text=True, timeout=timeout,
                                        start_new_session=True)
            except subprocess.TimeoutExpired:
                logger.warn(f"{label} timed out after {timeout}s "
                     f"(attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            if attempt < max_retries - 1:
                logger.warn(f"{label} call failed (exit {result.returncode}), "
                     f"retrying... (attempt {attempt + 1}/{max_retries})")
                time.sleep(2)
            else:
                logger.warn(f"{label} call failed after {max_retries} attempts "
                     f"(exit {result.returncode})")

        return ""

    def stream(self, prompt: str, *,
               label: str = "",
               timeout: int = 1800,
               max_retries: int = 3) -> int:
        """Send prompt with streaming output (capture_output=False).

        Not part of LLMProvider Protocol -- ClaudeCLI-specific.
        synthesize() checks hasattr(llm, 'stream') before calling.
        Returns exit code of last attempt.
        """
        if self._dry_run:
            logger.info(f"[DRY RUN] {label} prompt ({len(prompt)} chars)")
            return 0

        cmd = ['claude', '-p', '-', '--model', self._model,
               '--dangerously-skip-permissions']
        last_rc = 1

        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    cmd, input=prompt, capture_output=False, text=True,
                    timeout=timeout, start_new_session=True
                )
                last_rc = result.returncode
                if result.returncode == 0:
                    return 0
                logger.warn(f"{label} exited with code {result.returncode} "
                     f"(attempt {attempt + 1}/{max_retries})")
            except subprocess.TimeoutExpired:
                last_rc = 1
                logger.warn(f"{label} timed out after {timeout}s "
                     f"(attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                logger.info(f"Retrying {label} "
                     f"(attempt {attempt + 2}/{max_retries})...")
                time.sleep(5)

        return last_rc


