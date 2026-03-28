"""Generic parsing utilities: JSON extraction, frontmatter parsing."""

import json
import re
from pathlib import Path


def extract_json(text: str) -> dict:
    """Try to extract a JSON object from text, handling fences and extra content."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[^{}]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"speaker": "FALLBACK",
            "reasoning": "could not parse orchestrator response"}


def parse_frontmatter(path: Path) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Raises ValueError if no frontmatter.

    Manual regex parsing -- only supports flat key:value pairs.
    Nested YAML, multi-line values, or quoted strings are not handled.
    This is intentional to avoid a pyyaml dependency (stdlib-only design).
    """
    content = path.read_text(encoding="utf-8")
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    return match.group(1), content[match.end():]
