"""CLI argument parsing and path resolution utilities.

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
from pathlib import Path

from forge.utils.logger import logger


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
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


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    """Resolve project root, topic path, and optional resume dir.
    Returns (project_root, topic_path, resume_dir).
    """
    # Find project root by walking up to CLAUDE.md
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    if not (project_root / "CLAUDE.md").exists():
        project_root = project_root.parent
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
