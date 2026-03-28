"""Synthesis-driven functions: synthesize discussion and review quality."""

import json

from forge.llm import ClaudeCLI
from forge.utils.parsers import extract_json
from forge.models import Session
from forge.prompts import load_template
from forge.roles import RoleStore
from forge.session_io import SessionManager
from forge.utils.logger import logger, BOLD, NC


class SynthesisService:
    """Encapsulates synthesis and review operations."""

    def __init__(self, llm: ClaudeCLI, smgr: SessionManager, role_store: RoleStore) -> None:
        self._llm = llm
        self._smgr = smgr
        self._role_store = role_store

    def synthesize(self, topic_body: str) -> None:
        session = self._smgr.session

        print(f"\n{BOLD}--- Synthesizing reference document ---{NC}")

        synth_persona = self._role_store.get_synthesizer_persona()
        if synth_persona is None:
            logger.warn("Synthesizer role not found -- skipping synthesis")
            return

        synthesis_file = session.work_dir / "synthesis.md"

        # Build notes inventory
        notes_inventory_lines = []
        for p in sorted(session.notes_dir.rglob("*.md")):
            if p.name != "files-read.md":
                rel = p.relative_to(session.notes_dir)
                notes_inventory_lines.append(f"{rel} ({p.stat().st_size} bytes)")
        notes_inventory = "\n".join(notes_inventory_lines)

        # Check for archived previous synthesis (from --feedback runs)
        prev_synthesis_block = ""
        archived = sorted(session.work_dir.glob("synthesis-*.md"))
        if archived:
            latest_archived = archived[-1]
            prev_synthesis_block = (
                f"\nPREVIOUS SYNTHESIS: {latest_archived}\n"
                f"Read this to understand the prior conclusions. The human provided\n"
                f"feedback that triggered additional discussion -- focus on what changed.\n"
            )

        synth_prompt = load_template("synthesize",
                                      synth_persona=synth_persona,
                                      topic_body=topic_body,
                                      notes_dir=session.notes_dir,
                                      notes_inventory=notes_inventory,
                                      transcript_path=session.transcript,
                                      closing_path=session.work_dir / "closing.md",
                                      prev_synthesis_block=prev_synthesis_block,
                                      synthesis_file=synthesis_file)

        if self._llm.dry_run:
            self._llm.complete(synth_prompt, label="Synthesizer")
            synthesis_file.write_text("[dry run synthesis]\n", encoding="utf-8")
            return

        logger.info("Running synthesizer (this may take a few minutes)...")
        if hasattr(self._llm, 'stream'):
            synth_timeout = 1800
            synth_retries = 3
            logger.info(f"Synthesizer timeout: {synth_timeout}s x {synth_retries} retries")
            for attempt in range(synth_retries):
                if attempt > 0 and synthesis_file.exists():
                    backup = synthesis_file.with_suffix(f".attempt{attempt}.md")
                    synthesis_file.rename(backup)
                    logger.info(f"Moved partial synthesis to {backup.name}")
                rc = self._llm.stream(synth_prompt, label="Synthesizer",
                                timeout=synth_timeout, max_retries=1)
                if rc == 0:
                    break
                if attempt < synth_retries - 1:
                    logger.info(f"Retrying synthesizer "
                         f"(attempt {attempt + 2}/{synth_retries})...")
        else:
            result = self._llm.complete(synth_prompt, label="Synthesizer",
                                  timeout=1800)
            if result:
                synthesis_file.write_text(result, encoding="utf-8")

        if synthesis_file.exists():
            lines = len(synthesis_file.read_text(encoding="utf-8").splitlines())
            logger.ok(f"Synthesis written to {synthesis_file} ({lines} lines)")
        else:
            logger.warn(f"Synthesizer did not produce {synthesis_file}")

    def review(self) -> dict:
        """Review synthesis for accuracy against transcript and closing."""
        session = self._smgr.session
        synthesis_file = session.work_dir / "synthesis.md"
        closing_file = session.work_dir / "closing.md"

        if not synthesis_file.exists() or not closing_file.exists():
            return {"status": "APPROVED", "notes": "missing files, skipping review"}

        print(f"\n{BOLD}--- Reviewing synthesis ---{NC}")

        prompt = load_template("synthesis_review",
                               transcript_path=session.transcript,
                               closing_path=closing_file,
                               synthesis_path=synthesis_file)

        raw = self._llm.complete(prompt, label="Synthesis review", timeout=600)
        if not raw:
            return {"status": "APPROVED",
                    "notes": "dry run" if self._llm.dry_run else "review call failed, assuming pass"}

        result = extract_json(raw)

        review_file = session.work_dir / "review.json"
        review_file.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                               encoding="utf-8")

        status = result.get("status", "APPROVED")
        if status == "APPROVED":
            logger.ok(f"Synthesis approved: {result.get('notes', '')[:100]}")
        else:
            issues = result.get("issues", [])
            logger.warn(f"Synthesis review found {len(issues)} issue(s)")
            for issue in issues[:5]:
                logger.warn(f"  [{issue.get('type', '?')}] {issue.get('description', '')[:80]}")

        return result
