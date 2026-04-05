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
        
        # Initialize the official Audit Controller for high-fidelity replay analysis
        self.audit_controller = AuditController(
            config_dict=config_dict,
            logger=logger,
            data_root=data_root
        )

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
        Darwinian Comparison (v3.1): Evaluates PnL, forensic intelligence, and execution efficiency.
        Penalizes toxic wins, structural collapses, and catastrophic misses.
        Rewards smart capital preservation and efficient execution.

        Score Ladder (representative scenarios):
          TP_HIT (clean, fast):              100
          TP_HIT (clean, slow >48h):          85
          NEUTRAL (justified surrender):      75
          NEUTRAL (baseline):                 60
          TP_HIT (LOGIC_FAILURE):             45
          NEITHER (baseline, unfilled):       40
          NEITHER (catastrophic miss):        20
          SL_HIT (clean):                     15
          SL_HIT (LOGIC_FAILURE):            -25
        """

        def get_fitness_score(outcome: Dict[str, Any]) -> float:
            res = str(outcome.get('tp_sl_result', 'N/A')).upper()
            is_filled = outcome.get('is_filled', False)
            metrics = outcome.get('trade_execution_metrics', {})
            verdict = outcome.get('forensic_verdict', {})

            # --- 1. Base PnL Score ---
            base_scores = {
                "TP_HIT": 100.0,
                "NEUTRAL": 60.0,
                "NEITHER": 40.0,
                "SL_HIT": 15.0,
                "N/A": 0.0
            }
            score = base_scores.get(res, 0.0)

            # --- 2. Execution Quality Penalty (ALL filled trades) ---
            if is_filled:
                mae_tier = str(metrics.get('mae_stress_tier', '')).upper()
                mae_pct = float(metrics.get('mae_stress_level_pct', 0.0))
                hours = float(metrics.get('actual_hours', 0.0))

                # LOGIC_FAILURE or MAE >= 100%: Structural defense collapsed
                if mae_tier == "LOGIC_FAILURE" or mae_pct >= 100.0:
                    score -= 40.0
                elif mae_tier == "LUCK":
                    score -= 20.0

                # Slow capital lock penalty (only for directional trades)
                if res in ("TP_HIT", "NEITHER") and hours > 48.0:
                    score -= 15.0

            # --- 3. Forensic Verdict Modifiers ---
            # Smart Surrender: Disciplined inaction in a dead market
            if verdict.get('is_justified_surrender') is True:
                score += 15.0

            # Catastrophic Miss: Directional opinion correct, but order never filled
            if verdict.get('is_catastrophic_miss') is True:
                score -= 20.0

            return score

        old_score = get_fitness_score(old_outcome)
        new_score = get_fitness_score(new_outcome)

        old_res = str(old_outcome.get('tp_sl_result', 'N/A')).upper()
        new_res = str(new_outcome.get('tp_sl_result', 'N/A')).upper()

        # Dimension 1: Absolute Fitness Resolution
        if new_score > old_score:
            logger.info(f"Sandbox: [IMPROVEMENT] Darwinian score: {old_score} -> {new_score} ({old_res} -> {new_res})")
            return True
        if new_score < old_score:
            logger.info(f"Sandbox: [NO_IMPROVEMENT] Darwinian score: {old_score} -> {new_score} ({old_res} -> {new_res})")
            return False

        # Dimension 2: Execution Efficiency Tie-Breakers (same score)
        old_filled = old_outcome.get('is_filled', False)
        new_filled = new_outcome.get('is_filled', False)
        old_metrics = old_outcome.get('trade_execution_metrics', {})
        new_metrics = new_outcome.get('trade_execution_metrics', {})

        # Tie-breaker A: MAE Stress Reduction (only when BOTH trades were physically filled)
        if old_filled and new_filled:
            old_mae = float(old_metrics.get('mae_stress_level_pct', 100.0))
            new_mae = float(new_metrics.get('mae_stress_level_pct', 100.0))

            sandbox_cfg = self.config_dict.get('sandbox', {})
            mae_sig = float(sandbox_cfg.get('mae_significance_threshold', 15.0))
            mae_imp = float(sandbox_cfg.get('mae_improvement_threshold', 5.0))

            if old_mae > mae_sig and (old_mae - new_mae) >= mae_imp:
                logger.info(f"Sandbox: [REFINEMENT] MAE tiebreak: {old_mae}% -> {new_mae}%")
                return True

        # Tie-breaker B: Capital Velocity (Time Efficiency)
        old_time = float(old_metrics.get('actual_hours', 1000.0))
        new_time = float(new_metrics.get('actual_hours', 1000.0))
        if new_res == "TP_HIT" and (old_time - new_time) >= 4.0:
            logger.info(f"Sandbox: [REFINEMENT] Time efficiency: {old_time}h -> {new_time}h")
            return True

        logger.info(f"Sandbox: [STABLE] Darwinian score: {old_score} == {new_score} ({old_res} -> {new_res})")
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

        # v6.12 Hardening: Configuration-driven acceptance threshold
        sandbox_cfg = self.config_dict.get('sandbox', {})
        threshold = float(sandbox_cfg['acceptance_rate_threshold'])
        
        success_rate = len(accepted_cases) / total if total > 0 else 0
        is_accepted = success_rate >= threshold

        return {
            "is_accepted": is_accepted,
            "accepted_cases": accepted_cases,
            "rejected_cases": rejected_cases
        }
