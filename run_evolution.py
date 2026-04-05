#!/usr/bin/env python3
import os
import sys
import shutil
import logging
import argparse
from datetime import datetime
from typing import Dict
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_agent import EvolverAgent, EvolverConfig
from src.agent.evolver_sandbox import EvolverSandbox
from src.utils.pipeline_utils import add_data_path_argument
from src.utils.json_utils import load_json, save_json
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# v6.10: Global logger reference (will be properly initialized in Engine.__init__)
logger = None

class EvolutionEngine:
    """Singularity Meta-Evolution Engine (v6.1).

    Implements the 'Meta-Optimization' loop: 
    Ingest Audit Data -> Neural Mutation -> Sandbox Validation -> Atomic Config Commit.
    """
    def __init__(self, data_root: str, symbol: str):
        self.root = resolve_project_root()
        self.data_root = os.path.join(self.root, data_root)
        self.symbol = symbol
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
        
        self.logger.info(f"Engine: Oracle online [{self.symbol}]. Audit Trail Persistence: {log_path}")

    def _setup_evolution_dirs(self) -> Dict[str, str]:
        """Ensures the 'Evolution Black Box' directory hierarchy is initialized."""
        base_dir = os.path.join(self.data_root, "evolution")
        dirs = {
            "proposals": os.path.join(base_dir, "proposals"),
            "sandbox": os.path.join(base_dir, "sandbox_results"),
            "sandbox_accepted": os.path.join(base_dir, "sandbox_accepted"),
            "sandbox_rejected": os.path.join(base_dir, "sandbox_rejected")
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)
        return dirs

    def run_cycle(self, sample_size: int, run_sandbox: bool):
        """Standard Operating Procedure for the Universal Evolver."""
        self.logger.info("="*60)
        self.logger.info(f" EVOLUTION CYCLE START | Symbol: {self.symbol} | Sample: {sample_size} | Time: {datetime.now().isoformat()}")
        self.logger.info("="*60)
        from datetime import timezone
        evolver_at_dt = datetime.now(timezone.utc)
        evolver_at = evolver_at_dt.isoformat()
        ts_compact = evolver_at_dt.strftime("%Y%m%d_%H%M%S")

        # 1. Ingest Audit Evidence
        audit_dir = os.path.join(self.data_root, "audits")
        if not os.path.exists(audit_dir):
            self.logger.warning(f"Audit dir not found: {audit_dir}. Aborting cycle.")
            return

        # v6.11: Filter by symbol (Filename prefix + JSON validation)
        all_files = sorted([f for f in os.listdir(audit_dir) if f.endswith(".json")], reverse=True)
        files = []
        for f in all_files:
            if f.startswith(f"{self.symbol}_"):
                files.append(f)
            else:
                # Secondary deep-check if filename doesn't match standard pattern
                try:
                    report_preview = load_json(os.path.join(audit_dir, f))
                    if report_preview.get("symbol") == self.symbol:
                        files.append(f)
                except: continue

        if not files:
            self.logger.warning(f"No audit reports found for {self.symbol}. No evolutionary pressure detected.")
            return

        self.logger.info(f"Ingestion: Found {len(files)} reports for {self.symbol}. Selecting top {min(len(files), sample_size)} for analysis.")
        reports = []
        for f in files[:sample_size]:
            self.logger.info(f"Ingestion: [INGEST] -> {f}")
            report = load_json(os.path.join(audit_dir, f))
            if report: reports.append(report)

        # 2. Neural Meta-Optimization
        from src.utils.pipeline_utils import load_combined_config
        full_config = load_combined_config()
        
        ev_cfg = EvolverConfig.from_dict(full_config)
        
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

        instruction_paths = {
            "session_path": os.path.join(self.root, "src/agent/prompts/session.md"),
            "critic_path": os.path.join(self.root, "src/agent/prompts/critic.md"),
            "binary_star_path": os.path.join(self.root, "src/agent/prompts/binary_star.md")
        }
        
        # 3. Phase: Prototype Generation
        self.logger.info(f"Evolver: Initiating Neural Meta-Optimization ({ev_cfg.model} Inference)...")
        
        # v6.11: Inject RAW instruction contents to enable byte-perfect semantic refinement
        from src.utils.pipeline_utils import read_prompt_template
        instruction_contents = {
            "session": read_prompt_template(instruction_paths["session_path"]),
            "critic": read_prompt_template(instruction_paths["critic_path"]),
            "binary_star": read_prompt_template(instruction_paths["binary_star_path"])
        }

        evolution_result = evolver.evolve(
            audit_reports=reports,
            active_config=full_config,
            current_instructions=instruction_contents
        )
        
        # v6.11: Standardized Naming: {symbol}_evolution_{timestamp}
        ev_id = f"{self.symbol}_evolution_{ts_compact}"
        
        # Inject context for standalone sandbox/patch recovery
        evolution_result['metadata'] = {
            "symbol": self.symbol,
            "evolver_at": evolver_at,
            "audit_reports": files[:sample_size]
        }
        
        proposal_file = os.path.join(self.dirs['proposals'], f"{ev_id}.json")
        save_json(evolution_result, proposal_file)
        
        self.logger.info(f"Evolver: [PROPOSAL_GENERATED] -> {ev_id}")
        self.logger.info(f"Evolver: Rationale: {evolution_result.get('rationale', 'No rationale provided')[:200]}...")

        # 4. Phase: The Shadow Sandbox
        is_accepted = None
        if run_sandbox:
            self.logger.info(f"Sandbox: [BATCH_MODE] Validating {ev_id} against {len(reports)} historical cases.")
            sandbox = EvolverSandbox(
                self.api_key, 
                self.data_root,
                config_dict=full_config
            )
            validation = sandbox.run_batch_validation(
                audit_reports=reports,
                config_patch=evolution_result.get('config_patch'),
                instruction_patch=evolution_result.get('semantic_refinement')
            )
            
            accepted_total = len(validation.get('accepted_cases', []))
            rejected_total = len(validation.get('rejected_cases', []))
            is_accepted = validation.get('is_accepted', False)
            
            # v6.11: Sandbox Result Naming: {symbol}_evolution_sandbox_{timestamp}.json
            sandbox_id = f"{self.symbol}_evolution_sandbox_{ts_compact}"
            sandbox_file = os.path.join(self.dirs['sandbox'], f"{sandbox_id}.json")
            save_json(validation, sandbox_file)
            
            self.logger.info(f"Sandbox: Overall Result: {'ACCEPTED' if is_accepted else 'REJECTED'} (Accepted: {accepted_total}, Rejected: {rejected_total})")
        else:
            self.logger.info(f"Sandbox: [PASSIVE_MODE] Bypassing validation for {ev_id}. Proposal remains in 'proposals'.")
        
        # 5. Routing: Atomic Commit vs Rejection vs Passive
        if is_accepted is True:
            self.logger.info(f"Routing: EVOLUTION VALIDATED [{ev_id}]. Moving to 'sandbox_accepted'...")
            accepted_file = os.path.join(self.dirs['sandbox_accepted'], f"{ev_id}.json")
            shutil.move(proposal_file, accepted_file)

        elif is_accepted is False:
            self.logger.warning(f"Routing: EVOLUTION REJECTED [{ev_id}]. Regression risk detected. Moving to 'sandbox_rejected'...")
            rejected_file = os.path.join(self.dirs['sandbox_rejected'], f"{ev_id}.json")
            shutil.move(proposal_file, rejected_file)
        else:
            # is_accepted is None (Sandbox was not run)
            self.logger.info(f"Routing: Passive completion. Proposal isolated for review: {os.path.basename(proposal_file)}")

        timestamp_now = datetime.now().strftime("%H:%M:%S")
        self.logger.info(f"--- Evolution Cycle Complete | Duration: {timestamp_now} ---")

def main():
    parser = argparse.ArgumentParser(description="Singularity Meta-Evolution Engine (v6.1)")
    parser.add_argument("--symbol", type=str, default=None, help="Trading symbol for analysis (default: from config)")
    parser.add_argument("--samples", type=int, default=None, help="Number of audit reports to ingest (default: from config)")
    parser.add_argument("--sandbox", action="store_true", help="Activate Sandbox validation")
    add_data_path_argument(parser, required=True)
    
    args = parser.parse_args()
    data_root = args.path
    
    from src.utils.pipeline_utils import load_global_config
    g_cfg = load_global_config()
    
    symbol = args.symbol or g_cfg.get('system', {})['default_symbol']
    samples = args.samples or g_cfg.get('evolution', {})['default_samples']
        
    engine = EvolutionEngine(data_root, symbol=symbol)
    try:
        engine.run_cycle(sample_size=samples, run_sandbox=args.sandbox)
    except Exception as e:
        # Note: self.logger might not be initialized if __init__ fails
        print(f"Evolution Cycle Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
