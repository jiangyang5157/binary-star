import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import datetime
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CoachConfig:
    """Dataclass for type-safe Coach configuration."""
    model: str
    model_temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str
    reviewer_prompt_path: str
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, coach_cfg: Dict[str, Any], strat_cfg: Dict[str, Any], crit_cfg: Dict[str, Any], rev_cfg: Dict[str, Any], obs_cfg: Dict[str, Any], shared_cfg: Dict[str, Any], strategy_intent: str) -> "CoachConfig":
        """Factory method to extract coach config from decoupled components."""
        project_root = resolve_project_root()
        return cls(
            model=str(coach_cfg['model']),
            model_temperature=float(coach_cfg['model_temperature']),
            role_prompt_path=os.path.join(project_root, coach_cfg['role_definition_prompt']),
            strategist_prompt_path=os.path.join(project_root, strat_cfg['role_definition_prompt']),
            critic_prompt_path=os.path.join(project_root, crit_cfg['role_definition_prompt']),
            reviewer_prompt_path=os.path.join(project_root, rev_cfg['role_definition_prompt']),
            strategy_intent=strategy_intent,
            macro_interval=str(obs_cfg['macro_analysis_context']['time_interval']),
            micro_interval=str(obs_cfg['micro_analysis_context']['time_interval']),
            max_tool_iterations=int(shared_cfg['max_tool_iterations'])
        )

class CoachAgent(BaseAgent):
    """
    The Systemic Meta-Analyst (The Coach).
    
    This agent analyzes high-fidelity batches of historical forensic reviews to 
    identify recursive failures, logic gaps, and architectural weaknesses. 
    It suggests 'Forensic Patches'—optimized prompts or config changes—to 
    improve the overall intelligence of the trading triad.
    """
    def __init__(
        self, 
        config: CoachConfig, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: genai.Client
    ):
        """
        Initializes the Coach with a pre-assembled type-safe configuration.
        """
        self.config = config
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature,
            ai_client=ai_client,
            max_tool_iterations=self.config.max_tool_iterations,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max
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
        coach_result = self._execute_ai_cycle(prompt, agent_name="Coach")
        
        # Inject Evolution Fingerprint for Chain of Custody
        from src.utils.agent_utils import get_file_hash
        from src.utils.path_utils import resolve_project_root
        project_root = resolve_project_root()
        config_path = os.path.join(project_root, 'config', 'agent_config.yaml')
        
        coach_result["coaching_metadata"] = {
            "coach_hash": get_file_hash(self.config.role_prompt_path),
            "config_hash": get_file_hash(config_path),
            "coaching_timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        return coach_result

    def _build_prompt(self, review_history: List[Dict[str, Any]]) -> str:
        """
        Constructs the high-context analysis prompt.
        
        Injects the full current configuration and individual agent prompts 
        to ensure the Coach has the 'Semantic Map' required to suggest valid patches.
        """
        # Load linked agent prompts for holistic context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        reviewer_prompt = read_prompt_template(self.config.reviewer_prompt_path)
        
        context = {
            "batch_data": json.dumps(review_history, indent=2, ensure_ascii=False),
            "current_config": json.dumps(self.raw_config, indent=2, ensure_ascii=False),
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt,
            "reviewer_prompt": reviewer_prompt,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
