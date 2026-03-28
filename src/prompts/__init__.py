"""Prompt template loader for open-foundry.

Templates are .md files in this directory, loaded and rendered with
str.format() substitution.  Use {variable} placeholders in templates
and pass values via keyword arguments to load_template().

Literal braces in templates (e.g. JSON examples) must be doubled: {{ }}
"""

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load_template(name: str, **kwargs: object) -> str:
    """Load a .md template by name and substitute variables."""
    path = _DIR / f"{name}.md"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)
