"""Agent-driven functions: speak, execute, and status signal parsing."""

from pathlib import Path

from forge.llm import ClaudeCLI
from forge.models import Agent, ForumContext, Session
from forge.prompts import load_template
from forge.session_io import SessionManager


class AgentService:
    """Encapsulates agent speak and execute operations."""

    def __init__(self, llm: ClaudeCLI, smgr: SessionManager) -> None:
        self._llm = llm
        self._smgr = smgr

    @staticmethod
    def parse_status_signal(response: str) -> dict:
        """Extract status marker from last lines of agent response."""
        for line in reversed(response.strip().splitlines()):
            line = line.strip()
            if line == "[ANALYSIS_COMPLETE]":
                return {"signal": "ANALYSIS_COMPLETE"}
            if line.startswith("[NEEDS_DATA:") and line.endswith("]"):
                return {"signal": "NEEDS_DATA",
                        "item": line[len("[NEEDS_DATA:"):-1]}
            if line.startswith("[DISAGREE_WITH:") and line.endswith("]"):
                parts = line[len("[DISAGREE_WITH:"):-1].split(":", 1)
                return {"signal": "DISAGREE_WITH", "agent": parts[0],
                        "topic": parts[1] if len(parts) > 1 else ""}
            if line == "[INCONCLUSIVE]":
                return {"signal": "INCONCLUSIVE"}
        return {"signal": "NONE"}

    def speak(self, agent: Agent, ctx: ForumContext) -> str:
        session = self._smgr.session

        transcript_ctx = self._smgr.get_transcript_context(
            recent_turns=ctx.recent_window)

        refs_block = ""
        if ctx.mission_dir:
            refs_dir = ctx.mission_dir / "references"
            if refs_dir.is_dir() and any(refs_dir.iterdir()):
                refs_block = (
                    f"\nREFERENCE MATERIALS: {refs_dir}/\n"
                    f"Read files in this directory for background data provided\n"
                    f"by the mission author. Cite them when relevant.\n"
                )

        prompt = load_template("agent_speak",
                               agent_name=agent.name,
                               agent_persona=agent.persona,
                               mission_body=ctx.mission_body,
                               refs_block=refs_block,
                               transcript_ctx=transcript_ctx,
                               notes_dir=session.notes_dir,
                               turn_number=session.utterances + 1,
                               max_turns=ctx.max_turns)

        result = self._llm.complete(prompt, label=f"Agent {agent.name}")
        if not result:
            return f"[dry run response from {agent.name}]" if self._llm.dry_run else "[agent declined]"
        return result

    def execute(self, agent: Agent, ctx: ForumContext, task: dict) -> str:
        """Have an agent execute a specific implementation task."""
        session = self._smgr.session

        transcript_ctx = self._smgr.get_transcript_context(
            recent_turns=ctx.recent_window)

        refs_block = ""
        if ctx.mission_dir:
            refs_dir = ctx.mission_dir / "references"
            if refs_dir.is_dir() and any(refs_dir.iterdir()):
                refs_block = (
                    f"\nREFERENCE MATERIALS: {refs_dir}/\n"
                    f"Read files in this directory for specs, plans, and context.\n"
                )

        task_desc = task.get("task", "")
        verify_criteria = task.get("verify", "")

        verify_block = ""
        if verify_criteria:
            verify_block = f"\nVERIFICATION CRITERIA:\n{verify_criteria}\n"

        # Build handoff context from orchestrator reasoning
        handoff_parts = []
        reasoning = task.get("reasoning", "")
        if reasoning:
            handoff_parts.append(f"Decision: {reasoning}")
        recent_speakers = session.speakers_history[-5:] if session.speakers_history else []
        if recent_speakers:
            handoff_parts.append(f"Contributing agents: {', '.join(dict.fromkeys(recent_speakers))}")
        handoff_context = "\n".join(handoff_parts) if handoff_parts else "(none)"

        prompt = load_template("agent_execute",
                               agent_name=agent.name,
                               agent_persona=agent.persona,
                               mission_body=ctx.mission_body,
                               refs_block=refs_block,
                               task_desc=task_desc,
                               verify_block=verify_block,
                               handoff_context=handoff_context,
                               notes_dir=session.notes_dir,
                               transcript_ctx=transcript_ctx,
                               turn_number=session.utterances + 1,
                               max_turns=ctx.max_turns)

        result = self._llm.complete(prompt, label=f"Agent {agent.name} (execute)",
                              timeout=600)
        if not result:
            return (f"[dry run execution from {agent.name}]"
                    if self._llm.dry_run else "[agent declined]")
        return result
