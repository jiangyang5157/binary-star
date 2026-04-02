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

# Initialize symmetrical evolver logger
logger = setup_logger("RunEvolver")

class EvolverEngine:
    """
    Self-Evolution Control Engine (v5.3).
    Implements the 'Meta-Optimization' loop: 
    Ingest Forensics -> Generate Patch -> Sandbox Validation -> Atomic Commit.
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
        logger.info(f"--- Evolution Cycle Start: Analyzing last {sample_size} forensic reports ---")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Ingest Forensic Evidence
        strategy_dir = os.path.join(self.data_root, "strategies")
        if not os.path.exists(strategy_dir):
            logger.warning(f"Strategy base not found: {strategy_dir}. Aborting cycle.")
            return

        files = sorted([f for f in os.listdir(strategy_dir) if f.endswith(".json")], reverse=True)
        if not files:
            logger.warning("No forensic evidence found. No evolutionary pressure detected.")
            return

        reports = []
        for f in files[:sample_size]:
            report = load_json(os.path.join(strategy_dir, f))
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
            "strategist_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/strategist.md"),
            "critic_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/critic.md")
        }
        
        # 3. Phase: Prototype Generation
        evolution_result = evolver.evolve(
            forensic_reports=reports,
            active_config=config,
            current_prompts=prompts
        )
        
        ev_id = evolution_result.get('evolution_id', f"evo_{timestamp}")
        proposal_file = os.path.join(self.dirs['proposals'], f"{ev_id}.json")
        save_json(proposal_file, evolution_result)
        logger.info(f"Evolver: Mutated proposal generated -> {os.path.basename(proposal_file)}")

        # 4. Phase: The Shadow Sandbox
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
            logger.info(f"Sandbox: EVOLUTION VALIDATED [{ev_id}]. Committing to production...")
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
            logger.info(f"Evolver: Proposal isolated for manual forensic review -> {os.path.basename(refused_file)}")

def main():
    parser = argparse.ArgumentParser(description="The Meta-Evolution Engine (v5.3)")
    parser.add_argument("--samples", type=int, default=5, help="Number of forensic reports to ingest")
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
