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
    """
    The Meta-Optimizer responsible for Darwinian evolution of the system.
    Transforms audit failures into physical laws (Patches/Distillation).
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
        """
        Executes the main evolution cycle.
        
        Args:
            audit_reports: List of analyzed session results with outcomes.
            active_config: Current strategy_config.yaml state.
            current_prompts: Dict mapping 'session' and 'audit' to their prompt content.
        """
        try:
            # Batch audit reports for context
            logger.info(f"Evolver: Preparing context for {len(audit_reports)} session reports.")
            reports_json = json.dumps(audit_reports, indent=2)
            config_json = json.dumps(active_config, indent=2)
            prompts_json = json.dumps(current_prompts, indent=2)

            prompt = self._prepare_prompt(
                self.config.role_prompt_path,
                audit_reports_json=reports_json,
                active_config_yaml=config_json,
                current_prompt_md=prompts_json,
                strategy_intent=active_config.get('strategy_intent', "Market Survival")
            )

            logger.info("Evolver: Initiating distillation/patching cycle (Neural Inference)...")
            
            # Evolver always uses direct JSON (no Truth Bus needed for meta-analysis)
            evolution_result = self._execute_ai_cycle(
                payload=prompt,
                temperature=self.config.model_temperature,
                agent_name="Evolver_Meta",
                tools=None # Evolver is purely logical transformation for now
            )
            
            logger.info(f"Evolver: Neural analysis complete. Mutation Type: {evolution_result.get('type')}")
            return evolution_result
            
        except Exception as e:
            logger.error(f"Evolver: Evolution cycle failed: {e}")
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
        evolution_type = evolution_result.get('type')
        logger.info(f"Evolver: Applying mutation of type: {evolution_type}")
        
        # 1. Handle Configuration Overlays
        if evolution_type in ["PATCH", "FULL_UPGRADE"]:
            patch = evolution_result.get('proposed_patch', {})
            overlays = patch.get('patch_overlays', {})
            
            # --- v5.10 PHYSICAL HARDENING: Save Atomic Patch Record (The "留底" logic) ---
            try:
                from src.utils.pipeline_utils import resolve_data_root
                from src.utils.path_utils import resolve_project_root
                import yaml
                from datetime import datetime
                
                # Resolve Path via project standard
                data_root = resolve_data_root("once")
                patch_dir = os.path.join(resolve_project_root(), data_root, "patches")
                os.makedirs(patch_dir, exist_ok=True)
                
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                patch_filename = f"{symbol}_patch_{ts}.yaml"
                patch_path = os.path.join(patch_dir, patch_filename)
                
                with open(patch_path, 'w', encoding='utf-8') as f:
                    yaml.dump(overlays, f, default_flow_style=False)
                logger.info(f"Evolver: Atomic patch (physical record) saved to {patch_path}")
            except Exception as pe:
                logger.error(f"Evolver: Failed to save atomic patch record: {pe}")

            # --- DIRECT OVERWRITE: Apply live config change ---
            if ConfigPatcher.apply_patch(config_path, overlays):
                logger.info("Evolver: Configuration patch successfully merged into production.")
                success = True
        
        # 2. Handle Instruction Distillation
        if evolution_type in ["DISTILLATION", "FULL_UPGRADE"]:
            distillation = evolution_result.get('distilled_instruction', {})
            target = evolution_result.get('target_component', '')
            logger.info(f"Evolver: Processing instruction distillation for target: {target}")
            
            # Resolve target path from config
            from src.utils.pipeline_utils import load_config
            cfg = load_config()
            target_path = ""
            if "session" in target.lower():
                target_path = cfg.get('binary_star', {}).get('session', {}).get('role_definition_prompt', '')
            elif "audit" in target.lower():
                target_path = cfg.get('binary_star', {}).get('audit', {}).get('role_definition_prompt', '')
                
            if target_path:
                full_target_path = os.path.join(resolve_project_root(), target_path)
                if PromptDistiller.apply_distillation(full_target_path, distillation):
                    logger.info(f"Evolver: Prompt distillation successfully merged into {full_target_path}.")
                    success = True
            else:
                logger.warning(f"Evolver: Could not resolve physical path for target: {target}")
                
        return success
