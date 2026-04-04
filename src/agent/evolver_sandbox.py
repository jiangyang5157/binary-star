import logging
from typing import Dict, Any, List, Optional
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator

logger = logging.getLogger("EvolverSandbox")

class EvolverSandbox:
    """
    The 'Shadow Duelist' environment.
    Runs a parallel history recording against a proposed evolution patch.
    """
    def __init__(self, api_key: str, data_root: str):
        self.api_key = api_key
        self.data_root = data_root

    def validate_evolution(
        self, 
        failure_case: Dict[str, Any], 
        proposed_patch: Optional[Dict[str, Any]] = None,
        proposed_prompts: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Replays a historical failure case with new logic.
        
        Args:
            failure_case: The original audit session report (v3.5+ schema).
            proposed_patch: Potential strategy_config.yaml overrides.
            proposed_prompts: Potential prompt text overrides.
        """
        logger.info(f"Sandbox: Replaying session {failure_case.get('session_id')} in shadow mode.")
        
        # TODO yangj: apply proposed_patch and proposed_prompts to validate and revert if not PASS?

        # 1. Prepare Shadow Configuration (Baseline + Patch)
        shadow_config = failure_case.get('session', {}).get('metadata', {}).get('config_snapshot', {})
        if proposed_patch:
            # Apply patches if available
            for patch in proposed_patch:
                target = patch.get('target_key')
                value = patch.get('replaced_with')
                if target and value:
                    # TODO: Support nested keys if necessary, for now top-level
                    if target in shadow_config:
                        shadow_config[target] = value
                    elif 'regime_parameters' in shadow_config and target in shadow_config['regime_parameters']:
                        shadow_config['regime_parameters'][target] = value

        # 3. Instantiate Orchestrator (Injected with Shadow Logic)
        orchestrator = BinaryStarOrchestrator(
            config_dict=shadow_config,
            api_key=self.api_key,
            data_root=self.data_root
        )

        # 4. Replay
        
        case_metadata = failure_case.get('metadata', {})
        case_market_outcome = failure_case.get('market_outcome', {})
        case_tp_sl_result = case_market_outcome.get('tp_sl_result', "")
        case_session = failure_case.get('session', {})
        case_session_symbol = case_session.get('symbol', 'UNKNOWN')
        case_session_observation = case_session.get('observation', {})
        case_session_final_decision = case_session.get('final_decision', {})
        case_session_debate_history = case_session.get('debate_history', {})
        case_session_metadata = case_session.get('metadata', {})
        case_session__opinion = case_session_final_decision.get('opinion', "")

        new_session = orchestrator.execute_flow(case_session_observation, case_session_symbol)
        new_session_final_decision = new_session.get('final_decision', {})
        new_session_debate_history = new_session.get('debate_history', {})
        new_session_metadata = new_session.get('metadata', {})
        new_session_opinion = new_session_final_decision.get('opinion', "")

        # 4. Evolution Metric Analysis
        survival_improvement = False

        # Metric A
        if case_tp_sl_result == 'SL_HIT' and new_session_opinion != case_session__opinion:
            survival_improvement = True
            
        # Validation Verdict: Validated if ANY metric improved without catastrophic degradation
        is_validated = survival_improvement
        
        # Final Forensic Package
        return {
            "case_id": f"{case_session_observation['symbol']}_{case_session_observation['timestamp']}",
            "is_validated": is_validated,
            "metrics": {
                "case_session_final_decision": case_session_final_decision,
                "new_session_final_decision": new_session_final_decision,
                "case_session_debate_history": case_session_debate_history,
                "new_session_debate_history": new_session_debate_history,
            }
        }
