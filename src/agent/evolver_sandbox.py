import logging
import os
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
        session_id = audit_report.get('metadata', {}).get('audit_id', 'UNKNOWN_SESSION')
        logger.info(f"Sandbox: Replaying session {session_id} in shadow.")
        
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
        case_session = audit_report.get('session', {})
        case_session_symbol = case_session.get('symbol', 'UNKNOWN')
        case_session_observation = case_session.get('observation', {})

        new_session = orchestrator.execute_flow(case_session_observation, case_session_symbol)

        # 4. Evolution Metric Analysis: Did the new logic avoid the mistake?
        # TODO yangj: logic to determine if the new logic is better than the old logic
            
        
        # Final Forensic Package
        return {
            
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
        accepted_cases = []
        rejected_cases = []

        logger.info(f"Sandbox: Initiating batch validation for {len(audit_reports)} cases.")
        
        for idx, report in enumerate(audit_reports):
            new_audit_report = self.reply_audit_with_patch(report, config_patch, instruction_patch)
            results.append(new_audit_report)

            # TODO yangj: logic to determine if the new logic is better than the old logic
            rejected_cases.append(new_audit_report)
            
        return {
            "accepted_cases": accepted_cases,
            "rejected_cases": rejected_cases
        }
