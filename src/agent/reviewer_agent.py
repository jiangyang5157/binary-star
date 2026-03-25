import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from src.utils.agent_utils import read_prompt_template
from src.utils.path_utils import resolve_project_root

logger = logging.getLogger(__name__)

@dataclass
class ReviewerConfig:
    """Dataclass for type-safe Reviewer configuration."""
    model: str
    temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str
    macro_interval: str
    micro_interval: str

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "ReviewerConfig":
        """Factory method to extract reviewer config from the global config dict."""
        rev = full_config.get('reviewer', {}) # Fixed key: was 'review'
        obs = full_config.get('observer', {})
        strat = full_config.get('strategist', {})
        crit = full_config.get('critic', {})
        
        project_root = resolve_project_root()
        
        return cls(
            model=rev.get('model'),
            temperature=float(rev.get('temperature', 1.0)),
            role_prompt_path=os.path.join(project_root, rev.get('role_definition_prompt')),
            strategist_prompt_path=os.path.join(project_root, strat.get('role_definition_prompt')),
            critic_prompt_path=os.path.join(project_root, crit.get('role_definition_prompt')),
            macro_interval=obs.get('macro_analysis_context', {}).get('time_interval', '1h'),
            micro_interval=obs.get('micro_analysis_context', {}).get('time_interval', '15m')
        )

class ReviewerAgent:
    """
    Handles post-mortem auditing of trading strategy executions.
    Evaluates the reasoning triad (Draft -> Audit -> Synthesis) against 
    actual market outcomes to provide feedback for continuous improvement.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Reviewer with configuration and injected dependencies.
        
        Args:
            config_dict: Full application configuration dictionary.
            api_key: Gemini API key for fallback client initialization.
            ai_client: Optional pre-configured Gemini client for DI.
        """
        self.config = ReviewerConfig.from_dict(config_dict)
        self.raw_config = config_dict # Kept for prompt context if needed
        self.client = ai_client or genai.Client(api_key=api_key)

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None,
               chart_image_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Executes a multimodal post-mortem audit of a historical trading session.
        
        Args:
            historical_strategy: The full results from a previous triad run.
            actual_outcome: Data describing what actually happened in the market.
            current_observation: Latest market state for context.
            chart_image_paths: Optional paths to visual kline data.
            
        Returns:
            A structured JSON-like dictionary containing the audit findings.
        """
        logger.info(f"Reviewer: Auditing historical strategy session...")
        prompt = self._build_prompt(historical_strategy, actual_outcome, current_observation)
        return self._execute_ai_cycle(prompt, chart_image_paths)

    def _build_prompt(self, strategy: Dict[str, Any], 
                      outcome: Dict[str, Any], 
                      observation: Optional[Dict[str, Any]]) -> str:
        """Helper to construct and format the audit prompt."""
        template = read_prompt_template(self.config.role_prompt_path)
        
        # Load linked agent prompts for semantic context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        
        # Prepare context data
        context = {
            "historical_observation": json.dumps(strategy.get("observation"), indent=2, ensure_ascii=False),
            "actual_outcome_metrics": json.dumps(outcome, indent=2, ensure_ascii=False),
            "current_observation": json.dumps(observation, indent=2, ensure_ascii=False) if observation else "N/A",
            "current_config": json.dumps(self.raw_config, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(strategy.get("draft"), indent=2, ensure_ascii=False),
            "critique_against_draft_plan": json.dumps(strategy.get("critique"), indent=2, ensure_ascii=False),
            "final_decision": json.dumps(strategy.get("final_decision"), indent=2, ensure_ascii=False),
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
        }
        
        try:
            return template.format(**context)
        except KeyError as e:
            logger.warning(f"Reviewer: Missing prompt placeholder: {e}")
            return template

    def _execute_ai_cycle(self, prompt: str, image_paths: Optional[List[str]]) -> Dict[str, Any]:
        """Core AI execution logic for the audit session."""
        try:
            logger.info(f"Invoking Reviewer Agent ({self.config.model})...")
            
            # TODO: Implement multimodal support if image_paths are provided
            # For now, focus on text-based forensic audit
            contents = [prompt]
            
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=self.config.temperature,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Reviewer AI execution failed: {e}", exc_info=True)
            return {"error": "REVIEWER_EXECUTION_FAILURE", "details": str(e)}
