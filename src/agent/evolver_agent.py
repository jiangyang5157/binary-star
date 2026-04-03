import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger("EvolverAgent")

@dataclass(frozen=True)
class EvolverConfig(AgentConfig):
    """Configuration for the Evolver meta-agent."""
    model: str
    model_temperature: float
    role_prompt_path: str
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "EvolverConfig":
        """Factory method to extract evolver config from the standalone evolver node."""
        evo = cfg.get('evolver', {})
        shared = cfg.get('agent_model_shared_config', {})
        return cls(
            model=str(evo.get('model', 'gemini-2.5-flash')),
            role_prompt_path=os.path.join(resolve_project_root(), evo.get('role_definition_prompt', '')),
            model_temperature=float(evo.get('model_temperature', 0.0)),
            max_tool_iterations=int(shared.get('max_tool_iterations', 5))
        )

class EvolverAgent(BaseAgent):
    """The Meta-Optimizer for the Singularity Engine.

    Responsible for Darwinian evolution of the strategy and reasoning layers. 
    Transforms forensic audit failures into 'Physical Laws' (Configuration 
    Patches) and 'Semantic Refinements' (Prompt Distillation).
    """
    def __init__(
        self, 
        config: EvolverConfig, 
        ai_client: genai.Client,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int
    ):
        """Initializes the EvolverAgent with a type-safe configuration.

        Args:
            config: Encapsulated evolver parameters.
            ai_client: Authenticated Gemini client.
            api_timeout: Request timeout in seconds.
            retry_count: Maximum retry attempts.
            retry_multiplier: Retrying backoff multiplier.
            retry_min: Minimum retry delay.
            retry_max: Maximum retry delay.
        """
        super().__init__(
            config=config,
            ai_client=ai_client,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max
        )
        self.config = config

    def evolve(
        self, 
        audit_reports: List[Dict[str, Any]], 
        active_config: Dict[str, Any],
        current_prompts: Dict[str, str]
    ) -> Dict[str, Any]:
        """Executes the neural meta-optimization cycle.

        Analyzes recent forensic audit reports to identify systematic 
        logic failures or edge cases, then generates a corrective mutation.

        Args:
            audit_reports: List of analyzed session results with outcomes.
            active_config: Current active strategy_config.yaml state.
            current_prompts: Mapping of agent names to their prompt source code.

        Returns:
            A dictionary containing the mutation proposal and rationale.
        """
        try:
            logger.info(f"Evolver: Preparing context for {len(audit_reports)} forensic reports.")
            reports_json = json.dumps(audit_reports, indent=2)
            config_json = json.dumps(active_config, indent=2)
            prompts_json = json.dumps(current_prompts, indent=2)

            prompt = self._prepare_prompt(
                self.config.role_prompt_path,
                audit_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_json,
                strategy_intent=active_config.get('strategy_intent', "Market Survival"),
                trend_intensity_threshold=active_config.get('regime_parameters', {})['trend_intensity_threshold'],
                min_failure_instances=active_config.get('evolver', {})['min_failure_instances'],
                failure_ratio_threshold=active_config.get('evolver', {})['failure_ratio_threshold']
            )

            logger.info("Evolver: Initiating distillation/patching cycle (Neural Meta-Analysis)...")
            
            evolution_result = self._execute_ai_cycle(
                payload=prompt,
                temperature=self.config.model_temperature,
                agent_name="Evolver_Meta",
                tools=None
            )
            
            logger.info(f"Evolver: Mutation identified: {evolution_result.get('evolution_type')}")
            return evolution_result
            
        except Exception as e:
            logger.error(f"Evolver: Meta-optimization failed: {e}")
            raise

    def apply_patch(self, evolution_result: Dict[str, Any], config_path: str, symbol: str) -> bool:
        """
        Atomic Hardening of the system using the validated evolution result.
        
        Args:
            evolution_result: The structured output from self.evolve().
            config_path: Path to strategy_config.yaml.
            symbol: The trading symbol context for this patch.
        """
        from src.utils.evolution_utils import ConfigPatcher, PromptDistiller
        
        success = False
        evolution_type = evolution_result.get('evolution_type')
        logger.info(f"Evolver: Applying mutation of type: {evolution_type}")
        
        # 1. Handle Configuration Overlays (v5.10 Final Array Schema)
        config_patches = evolution_result.get('config_patch', [])
        if config_patches:
            overlays = {p.get('target_key'): p.get('replaced_with') for p in config_patches if p.get('target_key')}
            
            if overlays:
                # --- DIRECT OVERWRITE: Apply live config change ---
                if ConfigPatcher.apply_patch(config_path, overlays):
                    logger.info(f"Evolver: {len(overlays)} configuration parameters successfully merged.")
                    success = True
        
        # 2. Handle Semantic Refinement (v5.10 Final Array Schema)
        refinements = evolution_result.get('semantic_refinement', [])
        for refinement in refinements:
            target = refinement.get('target_module', '')
            anchor = refinement.get('anchor_text', '')
            new_logic = refinement.get('replaced_with', '')
            
            if not target or not anchor:
                continue

            logger.info(f"Evolver: Processing semantic refinement for target: {target}")
            
            # Resolve target path from config
            from src.utils.pipeline_utils import load_config
            from src.utils.path_utils import resolve_project_root
            cfg = load_config()
            target_path = ""
            
            if "session" in target.lower():
                target_path = cfg.get('binary_star', {}).get('session', {}).get('role_definition_prompt', '')
            elif "critic" in target.lower():
                target_path = cfg.get('binary_star', {}).get('critic', {}).get('role_definition_prompt', '')
            elif "binary_star" in target.lower():
                target_path = cfg.get('binary_star', {}).get('system_instruction', '')
                
            if target_path:
                full_target_path = os.path.join(resolve_project_root(), target_path)
                if PromptDistiller.apply_distillation(full_target_path, anchor, new_logic):
                    logger.info(f"Evolver: Prompt distillation successfully merged into {full_target_path}.")
                    success = True
            else:
                logger.warning(f"Evolver: Could not resolve physical path for target: {target}")
                
        return success
