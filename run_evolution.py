#!/usr/bin/env python3
import os
import sys
import json
import shutil
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_agent import EvolverAgent, EvolverConfig
from src.agent.evolver_sandbox import EvolverSandbox
from src.utils.pipeline_utils import load_config, resolve_data_root, add_data_root_argument
from src.utils.json_utils import load_json, save_json
from src.utils.logger_utils import setup_logger

# Initialize symmetrical evolution logger
logger = setup_logger("EvolutionEngine")

class EvolutionEngine:
    """Singularity Meta-Evolution Engine (v6.0).

    Implements the 'Meta-Optimization' loop: 
    Ingest Audit Data -> Neural Mutation -> Sandbox Validation -> Atomic Config Commit.
    """
    def __init__(self, data_root: str):
        self.data_root = os.path.join(PROJECT_ROOT, data_root)
        self.dirs = self._setup_evolution_dirs()
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            logger.critical("GEMINI_API_KEY not found. Evolution stalled.")
            sys.exit(1)

    def _setup_evolution_dirs(self) -> Dict[str, str]:
        """Ensures the 'Evolution Black Box' directory hierarchy is initialized."""
        base_dir = os.path.join(self.data_root, "evolution")
        dirs = {
            "proposals": os.path.join(base_dir, "proposals"),
            "sandbox": os.path.join(base_dir, "sandbox_results"),
            "applied": os.path.join(base_dir, "applied_patches"),
            "refusals": os.path.join(base_dir, "refusals")
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)
        return dirs

    def run_cycle(self, sample_size: int = 5):
        """Standard Operating Procedure for the Universal Evolver."""
        logger.info(f"--- Evolution Cycle Start: Analyzing last {sample_size} session reports ---")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Ingest Audit Evidence (Sessions)
        session_dir = os.path.join(self.data_root, "sessions")
        if not os.path.exists(session_dir):
            logger.warning(f"Session base not found: {session_dir}. Aborting cycle.")
            return

        files = sorted([f for f in os.listdir(session_dir) if f.endswith(".json")], reverse=True)
        if not files:
            logger.warning("No audit evidence (sessions) found. No evolutionary pressure detected.")
            return

        logger.info(f"Evolver: Found {len(files)} sessions. Ingesting top {min(len(files), sample_size)} candidates.")
        reports = []
        for f in files[:sample_size]:
            logger.info(f"Evolver: [INGEST] -> {f}")
            report = load_json(os.path.join(session_dir, f))
            if report: reports.append(report)

        # 2. Neural Meta-Optimization
        config = load_config()
        ev_cfg = EvolverConfig.from_dict(config)
        
        from google import genai
        from src.utils.pipeline_utils import load_global_config
        
        # Setup AI Client and Infrastructure Params
        client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1alpha'})
        g_cfg = load_global_config()
        gemini_net = g_cfg['network']['gemini']
        
        evolver = EvolverAgent(
            config=ev_cfg, 
            ai_client=client,
            api_timeout=int(gemini_net['api_timeout_seconds']),
            retry_count=int(gemini_net['retry_count']),
            retry_multiplier=float(gemini_net['retry_strategy']['multiplier']),
            retry_min=int(gemini_net['retry_strategy']['min_seconds']),
            retry_max=int(gemini_net['retry_strategy']['max_seconds'])
        )

        prompts = {
            "session_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/session.md"),
            "critic_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/critic.md"),
            "binary_star_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/binary_star.md")
        }
        
        # 3. Phase: Prototype Generation
        logger.info("Evolver: Initiating Neural Meta-Optimization (LLM Analysis)...")
        evolution_result = evolver.evolve(
            audit_reports=reports,
            active_config=config,
            current_prompts=prompts
        )
        
        ev_id = evolution_result.get('evolution_id', f"evolution_{timestamp}")
        proposal_file = os.path.join(self.dirs['proposals'], f"{ev_id}.json")
        save_json(proposal_file, evolution_result)
        logger.info(f"Evolver: Mutated proposal generated -> {os.path.basename(proposal_file)}")

        # 4. Phase: The Shadow Sandbox
        logger.info("Sandbox: Initiating validation of proposed mutations against failure cases...")
        sandbox = EvolverSandbox(self.api_key, self.data_root)
        validation = sandbox.validate_evolution(
            failure_case=reports[0],
            proposed_patch=evolution_result.get('proposed_patch'),
            proposed_prompts=evolution_result.get('distilled_instruction')
        )
        
        sandbox_file = os.path.join(self.dirs['sandbox'], f"{ev_id}_sandbox.json")
        save_json(sandbox_file, validation)
        
        # 5. Routing: Atomic Commit vs Rejection
        if validation.get('is_validated'):
            logger.info(f"Sandbox: EVOLUTION VALIDATED [{ev_id}]. Committing mutation...")
            applied_file = os.path.join(self.dirs['applied'], f"{ev_id}_applied.json")
            shutil.copy2(proposal_file, applied_file)
            
            if evolver.apply_patch(evolution_result, "config/strategy_config.yaml"):
                logger.info("System: Strategic core logic successfully mutated and hardened.")
            else:
                logger.error("System: Critical failure during atomic configuration merge.")
        else:
            logger.warning(f"Sandbox: EVOLUTION REJECTED [{ev_id}]. Regression risk detected.")
            refused_file = os.path.join(self.dirs['refusals'], f"{ev_id}_refused.json")
            shutil.move(proposal_file, refused_file)
            logger.info(f"Evolver: Proposal isolated for forensic review -> {os.path.basename(refused_file)}")

def main():
    parser = argparse.ArgumentParser(description="Singularity Meta-Evolution Engine (v6.0)")
    parser.add_argument("--samples", type=int, default=20, help="Number of forensic reports to ingest")
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod) required.")
        sys.exit(1)
        
    engine = EvolverEngine(data_root)
    try:
        engine.run_cycle(sample_size=args.samples)
    except Exception as e:
        logger.error(f"Evolution Cycle Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
