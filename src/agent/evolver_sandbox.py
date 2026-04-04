import logging
from typing import Dict, Any, List, Optional
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.utils.evolution_utils import PromptDistiller
from src.utils.pipeline_utils import read_prompt_template
from src.utils.path_utils import resolve_project_root

logger = logging.getLogger("EvolverSandbox")

class EvolverSandbox:
    """
    The 'Shadow Duelist' environment.
    Runs a parallel history recording against a proposed evolution patch.
    """
    def __init__(self, api_key: str, data_root: str, acceptance_threshold: float = 0.8):
        self.api_key = api_key
        self.data_root = data_root
        self.acceptance_threshold = acceptance_threshold

    def validate_evolution(
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
        session_id = audit_report.get('metadata', {}).get('audit_id', 'UNKNOWN_SESSION')
        logger.info(f"Sandbox: Replaying session {session_id} in shadow mode.")
        
        # 1. Prepare Proposed Configuration (Baseline + Patch)
        proposed_config = audit_report.get('session', {}).get('metadata', {}).get('config_snapshot', {})
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
                        patched_text = PromptDistiller.apply_distillation(baseline_text, agent_refinements)
                        instruction_overrides[agent_name] = patched_text
                        logger.info(f"Sandbox: Applied {len(agent_refinements)} refinements to {agent_name} logic.")
                    else:
                        # Even if no patch, we can still use the baseline or let it default to disk read
                        pass
                except Exception as e:
                    logger.warning(f"Sandbox: Could not load baseline for {agent_name} at {abs_path}: {e}")

        # 3. Instantiate Orchestrator (Injected with Proposed Logic)
        orchestrator = BinaryStarOrchestrator(
            config_dict=proposed_config,
            api_key=self.api_key,
            data_root=self.data_root,
            instruction_overrides=instruction_overrides
        )

        # 4. Replay
        
        case_metadata = audit_report.get('metadata', {})
        case_market_outcome = audit_report.get('market_outcome', {})
        case_tp_sl_result = case_market_outcome.get('tp_sl_result', "")
        case_session = audit_report.get('session', {})
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

        # 4. Evolution Metric Analysis: Did the new logic avoid the mistake?
        survival_improvement = False
        if case_tp_sl_result == 'SL_HIT' and new_session_opinion != case_session__opinion:
            # The new logic at least made a DIFFERENT decision in a losing trade
            survival_improvement = True
            
        is_validated = survival_improvement
        
        # Final Forensic Package
        return {
            "case_id": session_id,
            "is_validated": is_validated,
            "metrics": {
                "old_opinion": case_session__opinion,
                "new_opinion": new_session_opinion,
                "improvement": survival_improvement
            }
        }

    def run_batch_validation(
        self,
        audit_reports: List[Dict[str, Any]],
        config_patch: Optional[List[Dict[str, Any]]] = None,
        instruction_patch: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes a regression sweep across ALL provided audit reports.
        """
        results = []
        pass_cases = []
        failure_cases = []

        logger.info(f"Sandbox: Initiating batch validation for {len(audit_reports)} cases.")
        
        for idx, report in enumerate(audit_reports):
            case_id = report.get('metadata', {}).get('audit_id', f"case_{idx}")
            try:
                res = self.validate_evolution(report, config_patch, instruction_patch)
                results.append(res)
                if res.get('is_validated'):
                    pass_cases.append(case_id)
                else:
                    failure_cases.append(case_id)
            except Exception as e:
                logger.error(f"Sandbox: Failed to validate case {case_id}: {e}")
                failure_cases.append(case_id)

        success_count = len(pass_cases)
        total_count = len(audit_reports)
        success_rate = success_count / total_count if total_count > 0 else 0.0

        return {
            "is_validated": success_rate >= self.acceptance_threshold, # Threshold for overall acceptance
            "success_rate": success_rate,
            "pass_cases": pass_cases,
            "failure_cases": failure_cases,
            "detailed_results": results
        }
