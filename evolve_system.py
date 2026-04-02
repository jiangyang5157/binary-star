#!/usr/bin/env python3
import os
import sys
import json
import shutil
import logging
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_agent import EvolverAgent, EvolverConfig
from src.agent.evolver_sandbox import EvolverSandbox
from src.utils.pipeline_utils import load_config, resolve_data_root
from src.utils.json_utils import load_json, save_json
from src.utils.logger_utils import setup_logger

logger = setup_logger("EvolverSystem")

def setup_evolution_dirs(data_root: str) -> Dict[str, str]:
    """Ensures the 'Evolution Black Box' directory hierarchy is initialized."""
    base_dir = os.path.join(data_root, "evolution")
    dirs = {
        "proposals": os.path.join(base_dir, "proposals"),
        "sandbox": os.path.join(base_dir, "sandbox_results"),
        "applied": os.path.join(base_dir, "applied_patches"),
        "refusals": os.path.join(base_dir, "refusals")
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs

def run_evolution_cycle(data_root: str):
    """
    Standard Operating Procedure for the Universal Evolver (v4.4).
    """
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found.")
        return

    # 0. Initialize Storage
    evo_dirs = setup_evolution_dirs(data_root)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Load Forensic Evidence
    strategy_dir = os.path.join(data_root, "strategies")
    files = sorted([f for f in os.listdir(strategy_dir) if f.endswith(".json")], reverse=True)
    
    if not files:
        logger.warning("No forensic reports found. Evolution deferred.")
        return

    reports = []
    for f in files[:5]: # Ingest the last 5 forensic cases
        report = load_json(os.path.join(strategy_dir, f))
        if report:
            reports.append(report)

    # 2. Instantiate the Meta-Optimizer
    config = load_config()
    evolver_cfg = EvolverConfig.from_dict(config)
    evolver = EvolverAgent(evolver_cfg, api_key)

    prompts = {
        "strategist_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/strategist.md"),
        "critic_path": os.path.join(PROJECT_ROOT, "src/agent/prompts/critic.md")
    }
    
    # 3. Evolution Phase: Generate Prototype
    evolution_result = evolver.evolve(
        forensic_reports=reports,
        active_config=config,
        current_prompts=prompts
    )
    
    ev_id = evolution_result.get('evolution_id', f"evo_{timestamp}")
    proposal_file = os.path.join(evo_dirs['proposals'], f"{ev_id}.json")
    save_json(proposal_file, evolution_result)
    logger.info(f"Evolver: Proposal generated -> {proposal_file}")

    # 4. Validation Phase: The Shadow Duelist
    sandbox = EvolverSandbox(api_key, data_root)
    validation_status = sandbox.validate_evolution(
        failure_case=reports[0],
        proposed_patch=evolution_result.get('proposed_patch'),
        proposed_prompts=evolution_result.get('distilled_instruction')
    )
    
    sandbox_file = os.path.join(evo_dirs['sandbox'], f"{ev_id}_sandbox.json")
    save_json(sandbox_file, validation_status)
    
    # 5. Routing Phase: Apply or Discard
    if validation_status.get('is_validated'):
        logger.info(f"Sandbox: EVOLUTION VALIDATED [{ev_id}]. Hardening production...")
        
        # Move to applied_patches
        applied_file = os.path.join(evo_dirs['applied'], f"{ev_id}_applied.json")
        shutil.copy2(proposal_file, applied_file)
        
        # PHYSICAL COMMIT
        if evolver.apply_patch(evolution_result, "config/strategy_config.yaml"):
            logger.info("System: Evolution successfully merged into core logic.")
        else:
            logger.error("System: Critical failure during atomic merge phase.")
    else:
        logger.warning(f"Sandbox: EVOLUTION REJECTED [{ev_id}]. Regression detected.")
        
        # Move to refusals for forensic analysis
        refused_file = os.path.join(evo_dirs['refusals'], f"{ev_id}_refused.json")
        shutil.move(proposal_file, refused_file)
        logger.info(f"Evolver: Proposal isolated to refusals -> {refused_file}")

if __name__ == "__main__":
    DATA_ROOT = resolve_data_root("data/prod")
    run_evolution_cycle(DATA_ROOT)
