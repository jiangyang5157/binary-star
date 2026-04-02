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
        
        # 1. Setup Shadow Orchestrator
        # We clone the existing config and apply the patch overlay
        shadow_config = failure_case.get('regime_snapshot', {}).copy()
        if proposed_patch:
            shadow_config.update(proposed_patch.get('patch_overlays', {}))
        
        # 2. Instantiate Orchestrator (Injected with Shadow Logic)
        # Note: We use the same API key but a isolated data_root if needed
        orchestrator = BinaryStarOrchestrator(
            config_dict=shadow_config,
            api_key=self.api_key,
            data_root=self.data_root
        )
        
        # 3. Inject Distilled Prompts (Shadow Overrides)
        if proposed_prompts:
            if 'session' in proposed_prompts:
                orchestrator.session_agent.config.role_prompt_path = proposed_prompts['session_path']
            if 'audit' in proposed_prompts:
                orchestrator.audit.config.role_prompt_path = proposed_prompts['audit_path']

        # 4. Physical Playback
        # We feed the EXACT historical observation back into the machine
        observation = failure_case.get('observation')
        symbol = failure_case.get('symbol', "UNKNOWN")
        
        shadow_result = orchestrator.execute_flow(observation, symbol)
        
        # 5. Evolution Metric Analysis
        original_decision = failure_case.get('final_decision', {})
        new_decision = shadow_result.get('final_decision', {})
        
        survival_improvement = False
        # Logic: If original was a LOSS and shadow is NEUTRAL or better DLE -> Improvement
        # This requires outcome context which should be in the audit report
        # For now, we compare structural differences
        if original_decision.get('opinion') != new_decision.get('opinion'):
            survival_improvement = True
            
        return {
            "session_id": failure_case.get('session_id'),
            "is_validated": survival_improvement, # Simple stub for now
            "metrics": {
                "original_opinion": original_decision.get('opinion'),
                "shadow_opinion": new_decision.get('opinion'),
                "original_rounds": failure_case.get('metadata', {}).get('total_rounds'),
                "shadow_rounds": shadow_result.get('metadata', {}).get('total_rounds')
            },
            "audit_trail": shadow_result.get('debate_history')
        }
