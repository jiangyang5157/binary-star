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

# v6.10: Global logger reference (will be properly initialized in Engine.__init__)
logger = None

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
        
        # v6.10: Setup system-wide logging with physical persistence in data_root
        # Initializing the ROOT logger catches all child agents (Evolver, Sandbox, etc.)
        log_path = os.path.join(self.data_root, "evolution.log")
        setup_logger("", log_file=log_path) # Empty string means Root Logger
        self.logger = logging.getLogger("EvolutionEngine")
        
        if not self.api_key:
            self.logger.critical("GEMINI_API_KEY-VET_FAILED: Evolution Oracle offline.")
            sys.exit(1)
        
        self.logger.info(f"Engine: Oracle online. Audit Trail Persistence: {log_path}")

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
        self.logger.info("="*60)
        self.logger.info(f" EVOLUTION CYCLE START | Sample: {sample_size} | Time: {datetime.now().isoformat()}")
        self.logger.info("="*60)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Ingest Audit Evidence (Sessions)
        session_dir = os.path.join(self.data_root, "sessions")
        if not os.path.exists(session_dir):
            self.logger.warning(f"Session base not found: {session_dir}. Aborting cycle.")
            return

        files = sorted([f for f in os.listdir(session_dir) if f.endswith(".json")], reverse=True)
        if not files:
            self.logger.warning("No audit evidence (sessions) found. No evolutionary pressure detected.")
            return

        self.logger.info(f"Ingestion: Found {len(files)} sessions. Selecting top {min(len(files), sample_size)} for neural analysis.")
        reports = []
        for f in files[:sample_size]:
            self.logger.info(f"Ingestion: [INGEST] -> {f}")
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
        self.logger.info("Evolver: Initiating Neural Meta-Optimization (Gemini-Flash Inference)...")
        evolution_result = evolver.evolve(
            audit_reports=reports,
            active_config=config,
            current_prompts=prompts
        )
        
        ev_id = evolution_result.get('evolution_id', f"evolution_{timestamp}")
        proposal_file = os.path.join(self.dirs['proposals'], f"{ev_id}.json")
        save_json(proposal_file, evolution_result)
        
        mutation_summary = evolution_result.get('evolution_type', 'UNKNOWN')
        self.logger.info(f"Evolver: [PROPOSAL_GENERATED] -> {ev_id} | Type: {mutation_summary}")
        self.logger.info(f"Evolver: Rationale: {evolution_result.get('rationale', 'No rationale provided')[:200]}...")

        # 4. Phase: The Shadow Sandbox
        self.logger.info(f"Sandbox: Validating {ev_id} against primary failure case: {files[0]}")
        sandbox = EvolverSandbox(self.api_key, self.data_root)
        validation = sandbox.validate_evolution(
            failure_case=reports[0],
            proposed_patch=evolution_result.get('proposed_patch'),
            proposed_prompts=evolution_result.get('distilled_instruction')
        )
        
        sandbox_file = os.path.join(self.dirs['sandbox'], f"{ev_id}_sandbox.json")
        save_json(sandbox_file, validation)
        
        # 5. Routing: Atomic Commit vs Rejection
        is_valid = validation.get('is_validated', False)
        self.logger.info(f"Sandbox: Result Category: {'SUCCESS' if is_valid else 'FAILURE'}")
        self.logger.info(f"Sandbox: metrics -> Original: {validation.get('metrics', {}).get('original_opinion')} | Shadow: {validation.get('metrics', {}).get('shadow_opinion')}")

        if is_valid:
            self.logger.info(f"Routing: EVOLUTION VALIDATED [{ev_id}]. Initiating atomic system patching...")
            applied_file = os.path.join(self.dirs['applied'], f"{ev_id}_applied.json")
            shutil.copy2(proposal_file, applied_file)
            
            if evolver.apply_patch(evolution_result, "config/strategy_config.yaml", symbol=reports[0].get('symbol', 'BTCUSDT')):
                self.logger.info(f"System: Mutation {ev_id} successfully merged into strategic core.")
            else:
                self.logger.error(f"System: Critical failure during atomic merge of {ev_id}.")
        else:
            self.logger.warning(f"Routing: EVOLUTION REJECTED [{ev_id}]. Regression风险 detected.")
            refused_file = os.path.join(self.dirs['refusals'], f"{ev_id}_refused.json")
            shutil.move(proposal_file, refused_file)
            self.logger.info(f"Evolver: Proposal isolated for review: {os.path.basename(refused_file)}")

        self.logger.info(f"--- Evolution Cycle Complete | Duration: {datetime.now().strftime('%H:%M:%S')} ---")

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
        # Note: self.logger might not be initialized if __init__ fails
        print(f"Evolution Cycle Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
