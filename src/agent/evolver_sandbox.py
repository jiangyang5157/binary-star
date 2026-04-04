import logging
import os
import copy
from typing import Dict, Any, List, Optional
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.analyzer.audit_controller import AuditController
from src.utils.evolution_utils import PromptDistiller
from src.utils.pipeline_utils import read_prompt_template
from src.utils.path_utils import resolve_project_root

logger = logging.getLogger("EvolverSandbox")

class EvolverSandbox:
    """
    The 'Shadow Duelist' environment.
    Runs a parallel history recording against a proposed evolution patch.
    """
    def __init__(self, api_key: str, data_root: str, config_dict: Dict[str, Any]):
        self.api_key = api_key
        self.data_root = data_root
        self.config_dict = config_dict
        
        # v6.19: Initialize persistent Sandbox logging in data root
        self._setup_file_logging()
        
        # Initialize the official Audit Controller for high-fidelity replay analysis
        self.audit_controller = AuditController(
            config_dict=config_dict,
            logger=logger,
            data_root=data_root
        )

    def _setup_file_logging(self):
        """Configures a dedicated log file for the Sandbox session."""
        log_file = os.path.join(self.data_root, "sandbox.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Skip if handler already exists (avoid duplication in same process)
        if any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(log_file) for h in logger.handlers):
            return

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"Sandbox: Persistent logging initialized at {log_file}")

    def reply_audit_with_patch(
        self, 
        audit_report: Dict[str, Any], 
        config_patch: Optional[List[Dict[str, Any]]] = None,
        instruction_patch: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Replays a historical failure case with new logic.
        
        Args:
            audit_report: The original audit session report (v3.5+ schema).
            config_patch: Potential strategy_config.yaml overrides.
            instruction_patch: Potential instruction text overrides.
        """
        observation = audit_report.get('session', {}).get('observation', {})
        symbol = observation.get('symbol', 'UNKNOWN')
        obs_ts = observation["observed_at"]
        session_id = f"{symbol}_{obs_ts}"
        
        logger.info(f"Sandbox: Replaying session {session_id} in shadow.")
        
        # 1. Prepare Proposed Configuration (Baseline + Patch) - DEEP COPY for In-Memory Isolation
        baseline_config = audit_report.get('session', {}).get('metadata', {}).get('config_snapshot', {}) or {}
        proposed_config = copy.deepcopy(baseline_config)
        
        if config_patch:
            # Apply patches if available
            for patch in config_patch:
                target = patch.get('target_key')
                value = patch.get('replaced_with')
                t_path = patch.get('target_path', '') # Standard Evolver schema: "path.to.parent"
                
                if target is not None:
                    # Traverse to the target dictionary if target_path is provided
                    curr = proposed_config
                    path_valid = True
                    if t_path:
                        keys = t_path.split('.')
                        for k in keys:
                            if k not in curr or not isinstance(curr[k], dict):
                                logger.warning(f"Sandbox: SKIPPING patch - path node '{k}' not found in {t_path}")
                                path_valid = False
                                break
                            curr = curr[k]
                    
                    if path_valid:
                        # Update the final target
                        curr[target] = value
                        logger.info(f"Sandbox: Applied config patch: {t_path + '.' if t_path else ''}{target} = {value}")

        # 2. Prepare Proposed Instructions (Baseline + Patch) - IN-MEMORY ONLY
        instruction_overrides = {}
        if instruction_patch:
            logger.info("Sandbox: Distilling instruction refinements in-memory...")
            # We need to load the current templates to apply patches to them
            prompt_paths = {
                "session": "src/agent/prompts/session.md",
                "critic": "src/agent/prompts/critic.md",
                "binary_star": "src/agent/prompts/binary_star.md"
            }
            
            for agent_name, rel_path in prompt_paths.items():
                abs_path = os.path.join(resolve_project_root(), rel_path)
                try:
                    baseline_text = read_prompt_template(abs_path)
                    # Filter refinements for this specific agent
                    agent_refinements = [p for p in instruction_patch if p.get('target_module', '').lower() == agent_name]
                    
                    if agent_refinements:
                        patched_text = PromptDistiller.apply_batch_distillation(baseline_text, agent_refinements)
                        instruction_overrides[agent_name] = patched_text
                        logger.info(f"Sandbox: Applied {len(agent_refinements)} refinements to {agent_name} logic.")
                except Exception as e:
                    logger.warning(f"Sandbox: Could not load baseline for {agent_name} at {abs_path}: {e}")

        # 3. Instantiate Orchestrator (Injected with Proposed Logic)
        orchestrator = BinaryStarOrchestrator(
            config_dict=proposed_config,
            api_key=self.api_key,
            data_root=self.data_root,
            instruction_overrides=instruction_overrides
        )

        # 4. Replay Decision Flow
        new_session = orchestrator.execute_flow(observation, symbol)

        # 5. Run Formal Audit Flow (High-Fidelity Replay Analysis)
        # Directly anchor to the historical T1 timestamp (Assume presence per protocol hardening)
        from datetime import datetime
        metadata = audit_report.get('metadata', {})
        historical_t1 = datetime.fromisoformat(metadata["audit_at"].replace('Z', '+00:00'))
        logger.info(f"Sandbox: Anchoring audit to historical T1: {historical_t1.isoformat()}")

        # We use force=True to bypass maturity since we are replaying a historical session
        audit_bundle = self.audit_controller.audit_session_data(
            session=new_session,
            force=True,
            end_time=historical_t1
        )
        
        # Return the standardized Audit Bundle (Directly following v6.12 schema)
        return audit_bundle
    
    def _is_superior(self, old_outcome: Dict[str, Any], new_outcome: Dict[str, Any]) -> bool:
        """
        Darwinian Comparison: Determines if the new strategy outcome is objectively 
        better than the historical baseline.
        """
        old_res = str(old_outcome.get('tp_sl_result', 'N/A')).upper()
        new_res = str(new_outcome.get('tp_sl_result', 'N/A')).upper()
        
        # 1. Outcome Hierarchy (Higher is better)
        # TP_HIT (3) > NEITHER (2) > SL_HIT (1) > N/A (0)
        rank = {"TP_HIT": 3, "NEITHER": 2, "SL_HIT": 1, "N/A": 0}
        old_rank = rank.get(old_res, 0)
        new_rank = rank.get(new_res, 0)
        
        if new_rank > old_rank:
            logger.info(f"Sandbox: [IMPROVEMENT] Resolution upgrade: {old_res} -> {new_res}")
            return True
            
        # 2. Stress Reduction (MAE Improvement)
        # If the high-level outcome is the same, check if we reduced the risk/stress
        if new_rank == old_rank and new_rank > 0:
            old_metrics = old_outcome.get('trade_execution_metrics', {})
            new_metrics = new_outcome.get('trade_execution_metrics', {})
            
            old_mae = float(old_metrics.get('mae_stress_level_pct', 100))
            new_mae = float(new_metrics.get('mae_stress_level_pct', 100))
            
            # Fetch Darwinian thresholds from config
            evolver_cfg = self.config_dict.get('evolver', {})
            mae_sig = float(evolver_cfg['sandbox_mae_significance_threshold'])
            mae_imp = float(evolver_cfg['sandbox_mae_improvement_threshold'])

            # Improvement if MAE stress is significant and reduced by the threshold
            if old_mae > mae_sig and (old_mae - new_mae) > mae_imp:
                logger.info(f"Sandbox: [REFINEMENT] MAE Stress reduction: {old_mae}% -> {new_mae}% (Threshold: {mae_imp}%)")
                return True
                
        return False

    def run_batch_validation(
        self,
        audit_reports: List[Dict[str, Any]],
        config_patch: Optional[List[Dict[str, Any]]] = None,
        instruction_patch: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes a regression sweep across ALL provided audit reports.
        
        Logic: 
        1. Accepted: New result is strictly better (Loss -> Win/Neutral) or matches success.
        2. Rejected: New result is worse (Win -> Loss/Neutral) or remains a loss.
        """
        accepted_cases = []
        rejected_cases = []
        total = len(audit_reports)

        logger.info(f"Sandbox: Initiating batch validation for {total} cases.")
        
        for idx, report in enumerate(audit_reports):
            observation = report.get('session', {}).get('observation', {})
            symbol = observation.get('symbol', 'UNKNOWN')
            obs_ts = observation.get("observed_at", "N/A")
            session_id = f"{symbol}_{obs_ts}"
            
            logger.info(f"Sandbox: [Case {idx+1}/{total}] Processing {session_id}...")
            
            try:
                # 1. Execute Shadow Replay
                new_audit_report = self.reply_audit_with_patch(report, config_patch, instruction_patch)
                
                # 2. Forensic Comparison
                old_outcome = report.get('market_outcome', {})
                new_outcome = new_audit_report.get('market_outcome', {})
                
                if self._is_superior(old_outcome, new_outcome):
                    accepted_cases.append(new_audit_report)
                else:
                    rejected_cases.append(new_audit_report)
                
            except Exception as e:
                logger.error(f"Sandbox: Fatal error validating case {session_id}: {e}", exc_info=True)

        return {
            "is_accepted": len(accepted_cases) > len(rejected_cases),
            "accepted_cases": accepted_cases,
            "rejected_cases": rejected_cases
        }
