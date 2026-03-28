import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass
class ReviewerConfig:
    """Dataclass for type-safe Reviewer configuration."""
    model: str
    model_temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str
    macro_interval: str
    micro_interval: str
    execution_timeframe_interval: str
    strategy_intent: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "ReviewerConfig":
        """Factory method to extract reviewer config from the global config dict."""
        rev = full_config['reviewer']
        obs = full_config['observer']
        strat = full_config['strategist']
        crit = full_config['critic']
        
        project_root = resolve_project_root()
        
        return cls(
            model=str(rev['model']),
            model_temperature=float(rev['model_temperature']),
            role_prompt_path=os.path.join(project_root, rev['role_definition_prompt']),
            strategist_prompt_path=os.path.join(project_root, strat['role_definition_prompt']),
            critic_prompt_path=os.path.join(project_root, crit['role_definition_prompt']),
            macro_interval=str(obs['macro_analysis_context']['time_interval']),
            micro_interval=str(obs['micro_analysis_context']['time_interval']),
            execution_timeframe_interval=str(rev['execution_timeframe_interval']),
            strategy_intent=str(full_config['strategy_intent'])
        )

class ReviewerAgent(BaseAgent):
    """
    The High-Fidelity Forensic Auditor (The Reviewer).
    
    This agent performs post-mortem audits of historical trading sessions. 
    It evaluates the 'Reasoning Triad' (Draft -> Audit -> Synthesis) against 
    the actual market outcome to identify 'Delta Failures' and logic gaps.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Reviewer with multimodal configuration and dependencies.
        """
        self.config = ReviewerConfig.from_dict(config_dict)
        self.raw_config = config_dict
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature,
            api_key=api_key,
            ai_client=ai_client
        )

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None,
               visual_context: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Executes a multimodal post-mortem audit of a historical trading session.
        
        Args:
            historical_strategy: The full triad session (Draft, Critique, Final).
            actual_outcome: The PnL, TP/SL status, and execution metrics.
            current_observation: The market data at the time of review.
            visual_context: Dictionary of historical/current chart snapshots.
            
        Returns:
            A structured dictionary containing the forensic audit results.
        """
        logger.info(f"Reviewer: Auditing historical strategy session...")
        prompt_text = self._build_prompt(historical_strategy, actual_outcome, current_observation)
        
        # Build multimodal payload with forensic visual evidence
        contents = [prompt_text]
        if visual_context:
            labels = {
                "t0_macro": "T0 Historical Macro Snapshot",
                "t0_micro": "T0 Historical Micro Snapshot",
                "t1_macro": "T1 Current Macro Snapshot",
                "t1_micro": "T1 Current Micro Snapshot"
            }
            
            for key, path in visual_context.items():
                label = labels.get(key, f"Visual Supplement: {key}")
                if path and os.path.exists(path):
                    logger.info(f"Reviewer: Attaching forensic evidence: {label} ({path})")
                    with open(path, "rb") as f:
                        image_bytes = f.read()
                        contents.append(f"\n[FORENSIC ASSET: {label}]")
                        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
                else:
                    contents.append(f"\n[SYSTEM NOTICE: Forensic visual asset '{label}' missing from storage.]")

        # Execute high-fidelity review cycle via BaseAgent
        return self._execute_ai_cycle(contents, agent_name="Reviewer")

    def _build_prompt(self, strategy: Dict[str, Any], 
                      outcome: Dict[str, Any], 
                      observation: Optional[Dict[str, Any]]) -> str:
        """
        Constructs the high-context review prompt by injecting the full triad history.
        """
        # Load linked agent prompts for semantic ground-truth context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        
        # Prepare context data
        context = {
            "historical_observation": json.dumps(strategy.get("observation"), indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(strategy.get("draft"), indent=2, ensure_ascii=False),
            "critique_against_draft_plan": json.dumps(strategy.get("critique"), indent=2, ensure_ascii=False),
            "final_decision": json.dumps(strategy.get("final_decision"), indent=2, ensure_ascii=False),
            "actual_outcome_metrics": json.dumps(outcome, indent=2, ensure_ascii=False),
            "current_observation": json.dumps(observation, indent=2, ensure_ascii=False) if observation else "N/A",
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
