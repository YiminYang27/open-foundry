#!/usr/bin/env python3
"""Backward-compatible wrapper -- real implementation is in forge/cli.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forge import main  # noqa: E402

main()
