"""Pure data classes for the open-foundry orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Agent:
    name: str
    expertise: str
    persona: str


@dataclass
class Orchestrator:
    name: str
    pick_persona: str
    close_persona: str
    verify_persona: str = ""


@dataclass
class Session:
    work_dir: Path
    transcript: Path
    state_file: Path
    orch_log: Path
    utterances_dir: Path
    notes_dir: Path
    utterances: int = 0
    last_speaker: str = ""
    consecutive_count: int = 0
    speakers_history: list[str] | None = None
    interventions: list[dict] | None = None
    agent_statuses: dict | None = None

    def __post_init__(self):
        if self.speakers_history is None:
            self.speakers_history = []
        if self.interventions is None:
            self.interventions = []
        if self.agent_statuses is None:
            self.agent_statuses = {}


@dataclass
class MissionContext:
    """Aggregates parameters shared across discussion functions."""
    agents: list[Agent]
    orch: Orchestrator
    agent_list_str: str
    max_turns: int
    mission_body: str
    mission_dir: Path | None
    recent_window: int
