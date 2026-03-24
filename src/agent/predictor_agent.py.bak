import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from src.agent.observer_agent import ObserverAgent
from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from src.utils.agent_utils import load_prompt

logger = logging.getLogger(__name__)

class PredictorAgent:
    """
    Agent A: The Orchestrator (formerly Predictor).
    coordinates the 'Pure JSON Triad': Observer -> Strategist -> Critic -> Strategist.
    """
    def __init__(self, config: Dict[str, Any], symbol: str, api_key: str):
        self.config = config
        self.symbol = symbol
        self.api_key = api_key
        self.observer = ObserverAgent(config, symbol, api_key=api_key)
        self.strategist = StrategistAgent(config, api_key=api_key)
        self.critic = CriticAgent(config, api_key=api_key)
        
        # Guardrail Settings
        self.model_name = config['agent'].get('predictor_model', 'gemini-flash-latest')
        self.temp_final = config['agent'].get('predictor_temp_final', 0.1)
        self.prompt_path = os.path.join(
            config['paths']['prompts_dir'], 
            config['paths']['prompt_predictor_filename']
        )
        
        # Initialize GenAI client (mandatory)
        from google import genai
        self.client = genai.Client(api_key=self.api_key)

    def run_cycle(self, 
                 override_timestamp: Optional[datetime] = None,
                 data_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes the full Triad + Integrity Guardrail cycle.
        Returns a self-contained session JSON.
        """
        
        logger.info(f"--- ORCHESTRATION START: {self.symbol} ---")
        
        try:
            # 1. Observation
            logger.info("Stage 1/5: Observer (Fact Gathering)")
            observation = self.observer.observe(override_timestamp, data_dir)
            
            # 2. Draft
            logger.info("Stage 2/5: Strategist (Drafting)")
            draft = self.strategist.draft(observation)
            
            # 3. Audit
            logger.info("Stage 3/5: Critic (Adversarial Red-Team)")
            critique = self.critic.audit(observation, draft)
            
            # 4. Synthesis
            logger.info("Stage 4/5: Strategist (Synthesis)")
            synthesis = self.strategist.synthesize(observation, draft, critique)
            
            # 5. Integrity Guardrail (Pass 4)
            logger.info("Stage 5/5: Predictor (Integrity Guardrail)")
            final_decision = self._run_integrity_check(observation, draft, critique, synthesis)
            
            # Composite Report
            session_result = {
                "observation": observation,
                "draft": draft,
                "critique": critique,
                "final_decision": final_decision
            }
            
            logger.info(f"Orchestration Cycle Complete. Final Opinion: {final_decision.get('opinion', 'N/A')}")
            return session_result

        except Exception as e:
            logger.error(f"Orchestration Cycle Failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _run_integrity_check(self, obs, draft, critique, synthesis):
        if not self.client:
            return synthesis
            
        try:
            from google.genai import types
            prompt_template = load_prompt(self.prompt_path)
            
            prompt = prompt_template.format(
                observation=json.dumps(obs, indent=2),
                draft=json.dumps(draft, indent=2),
                critique=json.dumps(critique, indent=2),
                synthesis=json.dumps(synthesis, indent=2)
            )
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.temp_final,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.warning(f"Integrity check failed to execute: {e}. Falling back to Raw Synthesis.")
            return synthesis

    # Legacy alias for backward compatibility during transition
    def analyze(self, symbol: str, chart_image_paths: list[str], context_data: Dict[str, Any], current_position: str = "None") -> str:
        """DEPRECATED: Use run_cycle instead."""
        logger.warning("PredictorAgent.analyze() is deprecated. Redirecting to run_cycle().")
        res = self.run_cycle()
        return json.dumps(res, indent=2, ensure_ascii=False)
