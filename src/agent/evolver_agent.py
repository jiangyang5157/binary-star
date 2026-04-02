import os
import json
import logging
from typing import Dict, Any, List, Optional
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger("EvolverAgent")

class EvolverConfig(AgentConfig):
    """Configuration for the Evolver meta-agent."""
    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "EvolverConfig":
        # Evolver doesn't have a dedicated sub-node yet, 
        # using shared model/prompt paths for now.
        bs = cfg.get('binary_star', {})
        return cls(
            model=str(bs.get('model', "gemini-2.0-flash")),
            role_prompt_path=os.path.join(resolve_project_root(), "src/agent/prompts/evolver.md"),
            model_temperature=0.0 # Extreme determinism required for evolution
        )

class EvolverAgent(BaseAgent):
    """
    The Meta-Optimizer responsible for Darwinian evolution of the system.
    Transforms forensic failures into physical laws (Patches/Distillation).
    """
    def __init__(self, config: EvolverConfig, api_key: str):
        super().__init__(config, api_key)
        self.config = config

    def evolve(
        self, 
        forensic_reports: List[Dict[str, Any]], 
        active_config: Dict[str, Any],
        current_prompts: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Executes the main evolution cycle.
        
        Args:
            forensic_reports: List of analyzed session results with outcomes.
            active_config: Current strategy_config.yaml state.
            current_prompts: Dict mapping 'strategist' and 'critic' to their prompt content.
        """
        try:
            # Batch forensic reports for context
            reports_json = json.dumps(forensic_reports, indent=2)
            config_json = json.dumps(active_config, indent=2)
            prompts_json = json.dumps(current_prompts, indent=2)

            prompt = self._prepare_prompt(
                self.config.role_prompt_path,
                forensic_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_json,
                strategy_intent=active_config.get('strategy_intent', "Market Survival")
            )

            logger.info("Evolver: Initiating distillation/patching cycle across forensic batch...")
            
            # Evolver always uses direct JSON (no Truth Bus needed for meta-analysis)
            evolution_result = self._execute_ai_cycle(
                payload=prompt,
                temperature=self.config.model_temperature,
                agent_name="Evolver_Meta",
                tools=None # Evolver is purely logical transformation for now
            )
            
            return evolution_result
            
        except Exception as e:
            logger.error(f"Evolver: Evolution cycle failed: {e}")
            raise

    def apply_patch(self, evolution_result: Dict[str, Any], config_path: str) -> bool:
        """
        Atomic Hardening of the system using the validated evolution result.
        
        Args:
            evolution_result: The structured output from self.evolve().
            config_path: Path to strategy_config.yaml.
        """
        from src.utils.evolution_utils import ConfigPatcher, PromptDistiller
        
        success = False
        evolution_type = evolution_result.get('type')
        
        # 1. Handle Configuration Overlays
        if evolution_type in ["PATCH", "FULL_UPGRADE"]:
            patch = evolution_result.get('proposed_patch', {})
            overlays = patch.get('patch_overlays', {})
            if ConfigPatcher.apply_patch(config_path, overlays):
                logger.info("Evolver: Config patch successfully merged to prod.")
                success = True
        
        # 2. Handle Instruction Distillation
        if evolution_type in ["DISTILLATION", "FULL_UPGRADE"]:
            distillation = evolution_result.get('distilled_instruction', {})
            target = evolution_result.get('target_component', '')
            
            # Resolve target path from config
            from src.utils.pipeline_utils import load_config
            cfg = load_config()
            target_path = ""
            if "strategist" in target.lower():
                target_path = cfg.get('binary_star', {}).get('strategist', {}).get('role_definition_prompt', '')
            elif "critic" in target.lower():
                target_path = cfg.get('binary_star', {}).get('critic', {}).get('role_definition_prompt', '')
                
            if target_path and PromptDistiller.apply_distillation(os.path.join(resolve_project_root(), target_path), distillation):
                logger.info(f"Evolver: Prompt distillation merged to {target}.")
                success = True
                
        return success
