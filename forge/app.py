"""Application entry point -- composition root for the open-foundry orchestrator."""

import shutil

from forge.llm import LLMProviderFactory
from forge.models import ForumContext
from forge.roles import RoleStore, parse_mission
from forge.session_io import SessionManager
from forge.agents import AgentService
from forge.orchestrator import OrchestratorService
from forge.synthesis import SynthesisService
from forge.utils.cli import parse_args, resolve_paths
from forge.utils.logger import logger
from forge.workflow import ForumWorkflow


def main() -> None:
    args = parse_args()

    if args.feedback and not args.resume:
        logger.fatal("--feedback requires --resume to specify which session to continue")
    if args.synthesize_only and not args.resume:
        logger.fatal("--synthesize-only requires --resume to specify the session")

    project_root, mission_path, resume_dir = resolve_paths(args)

    # Check prerequisites
    if not shutil.which("claude"):
        logger.fatal("claude CLI not found in PATH")

    # Parse mission
    try:
        (agent_names, max_turns, model, orch_name, title, mission_body,
         execute_after) = parse_mission(mission_path)
    except ValueError as e:
        logger.fatal(str(e))

    # Apply CLI overrides
    if args.max_turns is not None:
        max_turns = args.max_turns
    if args.model is not None:
        model = args.model

    if not agent_names:
        logger.fatal("No agents defined in mission file")

    # Wire dependencies
    role_store = RoleStore(project_root / "roles")
    llm = LLMProviderFactory.create("claude-cli", model=model, dry_run=args.dry_run)

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
        mission_body=mission_body,
        mission_dir=mission_path.parent,
        recent_window=max(len(agents) + 2, 10),
    )

    # Session setup
    state = None
    if resume_dir:
        smgr, state = SessionManager.resume(resume_dir, agents)
    else:
        slug = (mission_path.parent.name if mission_path.name == "MISSION.md"
                else mission_path.stem)
        smgr = SessionManager.create(project_root, slug, mission_path,
                                     agents, title, max_turns, model, mission_body)
        smgr.update_state("starting", agents, max_turns, model,
                          str(mission_path))

    logger.set_session_log(smgr.session.work_dir / "runtime.log")

    # Build services
    agent_svc = AgentService(llm, smgr)
    orch_svc = OrchestratorService(llm, smgr)
    synth_svc = SynthesisService(llm, smgr, role_store)

    # Build and run workflow
    workflow = ForumWorkflow(smgr, ctx, llm, orch_svc, agent_svc, synth_svc)
    workflow.run(
        execute_after=execute_after,
        feedback=args.feedback,
        synthesize_only=args.synthesize_only,
        mission_path=mission_path,
        mission_source=str(mission_path),
        state=state,
    )
