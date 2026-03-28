"""Role and mission file loading for the open-foundry orchestrator.

Provides RoleStore for loading agent/orchestrator/synthesizer roles
from the roles/ directory, and parse_mission() for parsing MISSION.md files.
"""

import re
from pathlib import Path

from forge.log import fatal
from forge.models import Agent, Orchestrator


# ---------------------------------------------------------------------------
# Frontmatter parsing
# NOTE: Manual regex parsing -- only supports flat key:value pairs.
# Nested YAML, multi-line values, or quoted strings are not handled.
# This is intentional to avoid a pyyaml dependency (stdlib-only design).
# ---------------------------------------------------------------------------

def parse_frontmatter(path: Path) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Raises ValueError if no frontmatter."""
    content = path.read_text(encoding="utf-8")
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    return match.group(1), content[match.end():]


def parse_mission(path: Path) -> tuple[list[str], int, str, str, str, str, bool]:
    """Parse mission file.
    Returns (agent_names, max_turns, model, orchestrator_name, title, body,
             execute_after).
    """
    fm, body = parse_frontmatter(path)

    agents = []
    max_turns = 20
    model = "sonnet"
    orchestrator = "default"
    execute_after = False

    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("- role:"):
            agents.append(line.split(":", 1)[1].strip())
        elif line.startswith("max_turns:"):
            try:
                max_turns = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("model:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("orchestrator:"):
            orchestrator = line.split(":", 1)[1].strip()
        elif line.startswith("execute_after:"):
            execute_after = line.split(":", 1)[1].strip().lower() == "true"

    title = "Untitled Discussion"
    for bline in body.splitlines():
        bline = bline.strip()
        if bline.startswith("# "):
            title = bline[2:].strip()
            break

    return agents, max_turns, model, orchestrator, title, body.strip(), execute_after


class RoleStore:
    """Loads agent/orchestrator/synthesizer roles from the roles/ directory."""

    def __init__(self, roles_dir: Path) -> None:
        self._roles_dir = roles_dir

    @property
    def roles_dir(self) -> Path:
        return self._roles_dir

    def get_agent(self, name: str) -> Agent:
        """Load agent by name, searching subdirectories recursively."""
        candidate = self._roles_dir / f"{name}.md"
        if not candidate.exists():
            found = list(self._roles_dir.rglob(f"{name}.md"))
            if not found:
                fatal(f"Role file not found: {name}.md "
                      f"(searched in {self._roles_dir})")
            candidate = found[0]

        fm, body = parse_frontmatter(candidate)
        expertise = ""
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("expertise:"):
                expertise = line.split(":", 1)[1].strip()
                break

        return Agent(name=name, expertise=expertise, persona=body.strip())

    def get_orchestrator(self, name: str) -> Orchestrator:
        """Load orchestrator from roles/orchestrator/{name}.md."""
        orch_file = self._roles_dir / "orchestrator" / f"{name}.md"
        if not orch_file.exists():
            fatal(f"Orchestrator role not found: {orch_file} "
                  f"(referenced as '{name}' in topic)")

        try:
            _, body = parse_frontmatter(orch_file)
        except ValueError:
            body = orch_file.read_text(encoding="utf-8")

        pick_section = ""
        close_section = ""
        verify_section = ""

        sections = re.split(r'(?=^## )', body, flags=re.MULTILINE)
        for section in sections:
            if section.startswith("## Speaker Selection"):
                pick_section = re.sub(
                    r'^## Speaker Selection\s*\n', '', section).strip()
            elif section.startswith("## Closing Summary"):
                close_section = re.sub(
                    r'^## Closing Summary\s*\n', '', section).strip()
            elif section.startswith("## Verification"):
                verify_section = re.sub(
                    r'^## Verification\s*\n', '', section).strip()

        return Orchestrator(name=name, pick_persona=pick_section,
                            close_persona=close_section,
                            verify_persona=verify_section)

    def get_synthesizer_persona(self) -> str | None:
        """Load synthesizer persona from roles/general/synthesizer.md.
        Returns None if the role file does not exist.
        """
        synth_path = self._roles_dir / "general" / "synthesizer.md"
        if not synth_path.exists():
            return None

        try:
            _, body = parse_frontmatter(synth_path)
        except ValueError:
            body = synth_path.read_text(encoding="utf-8")

        return body.strip()
