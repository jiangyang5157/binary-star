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
        # v6.13 Schema: Extract from session.metadata.config_snapshot
        session_data = failure_case.get('session', {})
        metadata = session_data.get('metadata', {})
        shadow_config = metadata.get('config_snapshot', {}).copy()
        
        if proposed_patch:
            # v5.10 Schema: Reduce list of dicts {target_key, replaced_with} into a flat overlay
            overlays = {p.get('target_key'): p.get('replaced_with') for p in proposed_patch if p.get('target_key')}
            shadow_config.update(overlays)
        
        # 2. Instantiate Orchestrator (Injected with Shadow Logic)
        orchestrator = BinaryStarOrchestrator(
            config_dict=shadow_config,
            api_key=self.api_key,
            data_root=self.data_root
        )
        
        # 3. Inject Distilled Prompts (Shadow Overrides)
        if proposed_prompts:
            # v5.10 Schema: iterate through semantic_refinement list
            for refinement in proposed_prompts:
                target = refinement.get('target_module', '').lower()
                new_logic_content = refinement.get('replaced_with', '')
                anchor = refinement.get('anchor_text', '')
                
                # Note: For sandbox validation, we perform a temporary in-memory replacement 
                # in the agent's prompt template if possible, or swap the path if it's a file.
                # Since the orchestrator loads from path, we have to handle this carefully.
                # For now, we assume the physical merit of the new logic is captured.
                pass

        # 4. Physical Playback
        # v6.13 Schema: observation is inside session
        observation = session_data.get('observation')
        symbol = failure_case.get('session', {}).get('observation', {}).get('symbol', "UNKNOWN")
        
        shadow_result = orchestrator.execute_flow(observation, symbol)
        
        # 5. Evolution Metric Analysis
        # v6.13 Schema: final_decision is inside session
        original_decision = session_data.get('final_decision', {})
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
