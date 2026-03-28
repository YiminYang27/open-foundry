#!/usr/bin/env python3
"""
forge.cli -- Multi-agent discussion orchestrator

Runs a structured discussion between LLM agents with distinct
perspectives, moderated by an orchestrator that picks speakers
and detects consensus. All discussion is recorded to a readable
transcript.

Usage:
  ./scripts/forge.py <mission> [OPTIONS]

Arguments:
  <mission>   Path to a mission directory or MISSION.md file

Options:
  --max-turns N       Override max utterances (default: from mission file or 20)
  --model MODEL       Override model for all claude -p calls
  --resume DIR        Resume from a previous run directory
  --synthesize-only   Skip discussion, run finalize + synthesize (requires --resume)
  --dry-run           Print prompts without calling Claude
  --help              Show this help message

Intervention controls (during a running discussion):
  Ctrl+\\              Pause after current turn completes
  touch PAUSE         Pause from another terminal window

Examples:
  ./scripts/forge.py gold-price-outlook
  ./scripts/forge.py gold-price-outlook --max-turns 50 --model opus
  ./scripts/forge.py gold-price-outlook --resume gold-price-outlook-20260322-001929
  ./scripts/forge.py gold-price-outlook --resume gold-price-outlook-20260322-001929 --synthesize-only
  ./scripts/forge.py gold-price-outlook --model opus
"""

import argparse
import shutil
from pathlib import Path

from forge.llm import ClaudeCLI
from forge.models import ForumContext
from forge.roles import RoleStore, parse_mission
from forge.session_io import create_session, resume_session, update_state
from forge.utils.logger import logger
from forge.workflow import run_forum


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-agent discussion orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        add_help=True,
    )
    parser.add_argument("topic_file",
                        help="Mission slug or path (e.g. gold-price-outlook)")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="Override max utterances")
    parser.add_argument("--model", default=None,
                        help="Override model (opus/sonnet/haiku)")
    parser.add_argument("--resume", default=None, metavar="SESSION",
                        help="Resume session (slug-timestamp)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip discussion, run finalize + synthesize "
                             "(requires --resume)")
    parser.add_argument("--feedback", default=None, metavar="TEXT",
                        help="Inject human feedback into a completed session "
                             "and resume discussion")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling Claude")
    return parser.parse_args()


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    """Resolve project root, topic path, and optional resume dir.
    Returns (project_root, topic_path, resume_dir).
    """
    # Find project root by walking up to CLAUDE.md
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    if not (project_root / "CLAUDE.md").exists():
        project_root = project_root.parent

    topic_path = Path(args.topic_file)
    if not topic_path.is_absolute():
        missions_dir = project_root / "missions"
        candidate = missions_dir / topic_path
        if candidate.exists():
            topic_path = candidate
        else:
            topic_path = project_root / topic_path
    if topic_path.is_dir():
        mission_file = topic_path / "MISSION.md"
        if not mission_file.exists():
            logger.fatal(f"MISSION.md not found in {topic_path}")
        topic_path = mission_file
    if not topic_path.exists():
        logger.fatal(f"Mission not found: {topic_path}")

    resume_dir = None
    if args.resume:
        resume_dir = Path(args.resume)
        if not resume_dir.is_absolute():
            sessions_dir = project_root / "sessions"
            candidate = sessions_dir / resume_dir
            if candidate.exists():
                resume_dir = candidate
            else:
                resume_dir = project_root / resume_dir
        if not resume_dir.exists():
            logger.fatal(f"Resume directory not found: {resume_dir}")

    return project_root, topic_path, resume_dir


def main() -> None:
    args = _parse_args()

    if args.feedback and not args.resume:
        logger.fatal("--feedback requires --resume to specify which session to continue")
    if args.synthesize_only and not args.resume:
        logger.fatal("--synthesize-only requires --resume to specify the session")

    project_root, topic_path, resume_dir = _resolve_paths(args)

    # Check prerequisites
    if not shutil.which("claude"):
        logger.fatal("claude CLI not found in PATH")

    # Parse mission
    try:
        (agent_names, max_turns, model, orch_name, title, topic_body,
         execute_after) = parse_mission(topic_path)
    except ValueError as e:
        logger.fatal(str(e))

    # Apply CLI overrides
    if args.max_turns is not None:
        max_turns = args.max_turns
    if args.model is not None:
        model = args.model

    if not agent_names:
        logger.fatal("No agents defined in topic file")

    # Wire dependencies
    role_store = RoleStore(project_root / "roles")
    llm = ClaudeCLI(model=model, dry_run=args.dry_run)

    logger.info("Validating role files...")
    agents = [role_store.get_agent(name) for name in agent_names]
    logger.ok(f"All {len(agents)} role files validated")

    orch = role_store.get_orchestrator(orch_name)
    logger.info(f"Orchestrator: {orch_name}")

    ctx = ForumContext(
        agents=agents,
        orch=orch,
        agent_list_str="".join(f"- {a.name}: {a.expertise}\n" for a in agents),
        max_turns=max_turns,
        topic_body=topic_body,
        mission_dir=topic_path.parent,
        recent_window=max(len(agents) + 2, 10),
    )

    # Session setup
    state = None
    if resume_dir:
        session, state = resume_session(resume_dir, agents)
    else:
        slug = (topic_path.parent.name if topic_path.name == "MISSION.md"
                else topic_path.stem)
        session = create_session(project_root, slug, topic_path,
                                 agents, title, max_turns, model, topic_body)
        update_state(session, "starting", agents, max_turns, model,
                     str(topic_path))

    logger.set_session_log(session.work_dir / "runtime.log")

    # Run pipeline
    run_forum(session, ctx, llm, role_store,
              execute_after=execute_after,
              feedback=args.feedback,
              synthesize_only=args.synthesize_only,
              topic_path=topic_path,
              mission_source=str(topic_path),
              state=state)


if __name__ == "__main__":
    main()
