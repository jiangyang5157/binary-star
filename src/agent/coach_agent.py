import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass
class CoachConfig:
    """Dataclass for type-safe Coach configuration."""
    model: str
    temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "CoachConfig":
        """Factory method to extract coach config from the global config dict."""
        coach_cfg = full_config['coach']
        strat_cfg = full_config['strategist']
        crit_cfg = full_config['critic']
        
        project_root = resolve_project_root()
        
        return cls(
            model=str(coach_cfg['model']),
            temperature=float(coach_cfg['temperature']),
            role_prompt_path=os.path.join(project_root, coach_cfg['role_definition_prompt']),
            strategist_prompt_path=os.path.join(project_root, strat_cfg['role_definition_prompt']),
            critic_prompt_path=os.path.join(project_root, crit_cfg['role_definition_prompt'])
        )

class CoachAgent(BaseAgent):
    """
    The Systemic Meta-Analyst (The Coach).
    
    This agent analyzes high-fidelity batches of historical forensic reviews to 
    identify recursive failures, logic gaps, and architectural weaknesses. 
    It suggests 'Forensic Patches'—optimized prompts or config changes—to 
    improve the overall intelligence of the trading triad.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Coach with configuration and injected dependencies.
        """
        self.config = CoachConfig.from_dict(config_dict)
        self.raw_config = config_dict
        super().__init__(
            model=self.config.model,
            temperature=self.config.temperature,
            api_key=api_key,
            ai_client=ai_client
        )

    def analyze(self, review_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes a coaching session by analyzing a batch of historical reviews.
        
        Args:
            review_history: A list of consolidated forensic reports (triad + outcome).
            
        Returns:
            A structured dictionary containing systemic findings and suggested patches.
        """
        logger.info(f"Coach: Starting systemic analysis of {len(review_history)} forensic reports...")
        prompt = self._build_prompt(review_history)
        
        # Execute recursive analysis cycle via BaseAgent
        return self._execute_ai_cycle(prompt, agent_name="Coach")

    def _build_prompt(self, review_history: List[Dict[str, Any]]) -> str:
        """
        Constructs the high-context analysis prompt.
        
        Injects the full current configuration and individual agent prompts 
        to ensure the Coach has the 'Semantic Map' required to suggest valid patches.
        """
        # Load linked agent prompts for holistic context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        
        context = {
            "batch_data": json.dumps(review_history, indent=2, ensure_ascii=False),
            "current_config": json.dumps(self.raw_config, indent=2, ensure_ascii=False),
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
