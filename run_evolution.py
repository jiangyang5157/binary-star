#!/usr/bin/env python3
import os
import sys
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict
from dotenv import load_dotenv

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.evolver_agent import EvolverAgent, EvolverConfig
from src.utils.pipeline_utils import add_data_path_argument
from src.utils.json_utils import load_json, save_json
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# Global logger reference (will be properly initialized in Engine.__init__)
logger = None

class EvolutionEngine:
    """BinaryStar Meta-Evolution Engine.

    Implements the 'Meta-Optimization' loop: 
    Ingest Audit Data -> Neural Mutation -> Sandbox Validation -> Atomic Config Commit.
    """
    def __init__(self, data_root: str, symbol: str):
        self.root = resolve_project_root()
        self.data_root = os.path.join(self.root, data_root)
        self.symbol = symbol

        # Validate symbol is explicitly configured — no silent fallback
        from src.config.symbol_resolver import is_symbol_configured
        if not is_symbol_configured(self.symbol):
            self.logger = logging.getLogger("EvolutionEngine")
            self.logger.critical(
                "symbol '%s' is not configured in symbol_config.yaml", self.symbol
            )
            sys.exit(1)

        self.dirs = self._setup_evolution_dirs()
        load_dotenv()
        
        # Setup system-wide logging with physical persistence in data_root
        log_path = os.path.join(self.data_root, "evolution.log")
        setup_logger("", log_file=log_path,
                     max_bytes=10 * 1024 * 1024, backup_count=5)
        self.logger = logging.getLogger("EvolutionEngine")
        
        # Resolve API key based on active provider (decoupled)
        from src.utils.pipeline_utils import resolve_api_key
        self.api_key = resolve_api_key()
        
        if not self.api_key:
            self.logger.critical("API_KEY not found | evolution oracle offline")
            sys.exit(1)
        
        self.logger.info(f"oracle online | symbol={self.symbol} | log={log_path}")

    def _setup_evolution_dirs(self) -> Dict[str, str]:
        """Ensures the 'Evolution Black Box' directory hierarchy is initialized."""
        base_dir = os.path.join(self.data_root, "evolution")
        dirs = {
            "proposals": os.path.join(base_dir, "proposals")
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)
        return dirs

    def run_cycle(self, sample_size: int):
        """Standard Operating Procedure for the Universal Evolver."""
        self.logger.info(f"═══ EVOLUTION CYCLE START | symbol={self.symbol} | sample={sample_size} ═══")
        evolver_at_dt = datetime.now(timezone.utc)
        evolver_at = evolver_at_dt.isoformat()
        ts_compact = evolver_at_dt.strftime("%Y%m%d_%H%M%S")

        # 1. Ingest Audit Evidence
        audit_dir = os.path.join(self.data_root, "audits")
        if not os.path.exists(audit_dir):
            self.logger.warning(f"audit dir not found | path={audit_dir} | aborting cycle")
            return

        # Filter by symbol (Filename prefix + JSON validation)
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
                except Exception as e:
                    logger.warning(f"failed to read audit file | file={f} | error={e}")
                    continue

        if not files:
            self.logger.warning(f"no audit reports found | symbol={self.symbol} | no evolutionary pressure")
            return

        self.logger.info(f"found {len(files)} reports | symbol={self.symbol} | selecting top {min(len(files), sample_size)}")
        reports = []
        for f in files[:sample_size]:
            self.logger.info(f"ingesting report | file={f}")
            report = load_json(os.path.join(audit_dir, f))
            if report: reports.append(report)

        # 2. Neural Meta-Optimization
        from src.utils.pipeline_utils import load_combined_config
        from src.config.symbol_resolver import load_and_resolve_for_symbol

        # Resolve all configs with per-symbol overrides so the evolver
        # analyzes with the exact same config the sessions ran with
        full_config = load_and_resolve_for_symbol(self.symbol)

        ev_cfg = EvolverConfig.from_dict(full_config)
        
        from src.utils.pipeline_utils import load_global_config
        from src.infrastructure.ai_factory import AIFactory

        g_cfg = load_global_config()
        client = AIFactory.create_client(api_key=self.api_key, config_dict=g_cfg)
        llm_cfg = g_cfg['llm']

        evolver = EvolverAgent(
            config=ev_cfg,
            ai_client=client,
            api_timeout=int(llm_cfg['api_timeout_seconds']),
            retry_count=int(llm_cfg['retry_count']),
            retry_multiplier=float(llm_cfg['retry_strategy']['multiplier']),
            retry_min=int(llm_cfg['retry_strategy']['min_seconds']),
            retry_max=int(llm_cfg['retry_strategy']['max_seconds'])
        )

        instruction_paths = {
            "session_path": os.path.join(self.root, "config/prompts/session.md"),
            "critic_path": os.path.join(self.root, "config/prompts/critic.md"),
            "binary_star_path": os.path.join(self.root, "config/prompts/binary_star.md")
        }
        
        # 3. Phase: Prototype Generation
        self.logger.info(f"evolver started | model={ev_cfg.model}")
        
        # Inject RAW instruction contents to enable byte-perfect semantic refinement
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
        
        # Standardized Naming: {symbol}_evolution_{timestamp}
        ev_id = f"{self.symbol}_evolution_{ts_compact}"
        
        # Inject context for standalone sandbox/patch recovery
        evolution_result['metadata'] = {
            "symbol": self.symbol,
            "evolver_at": evolver_at,
            "audit_reports": files[:sample_size]
        }
        
        proposal_file = os.path.join(self.dirs['proposals'], f"{ev_id}.json")
        save_json(evolution_result, proposal_file)
        
        self.logger.info(f"proposal generated | id={ev_id}")
        self.logger.info(f"rationale | {evolution_result.get('rationale', 'No rationale provided')[:200]}...")

        timestamp_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.logger.info("─── EVOLUTION CYCLE COMPLETE ───")

def main():
    parser = argparse.ArgumentParser(description="BinaryStar Meta-Evolution Engine")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix (e.g. BTC)")
    parser.add_argument("--samples", type=int, default=None, help="Number of audit reports to ingest (required)")
    add_data_path_argument(parser, required=True)
    
    args = parser.parse_args()
    data_root = args.path
    
    from src.utils.symbol_utils import resolve_symbol
    symbol = resolve_symbol(args.symbol)
    samples = args.samples
    if samples is None:
        raise SystemExit("Error: --samples is required (number of audit reports to ingest).")

    engine = EvolutionEngine(data_root, symbol=symbol)
    try:
        engine.run_cycle(sample_size=samples)
    except Exception as e:
        # engine.__init__ guarantees self.logger exists if run_cycle() is reachable
        engine.logger.error(f"evolution cycle failed | error={e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
