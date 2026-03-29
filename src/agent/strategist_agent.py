import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.datetime_utils import get_interval_seconds
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__, propagate = True)

@dataclass(frozen=True)
class StrategistConfig:
    """Encapsulates configuration for the StrategistAgent."""
    model: str
    role_prompt_path: str
    model_temperature_draft: float
    model_temperature_synthesis: float
    min_trade_velocity: float
    stop_loss_buffer_min: float
    stop_loss_buffer_max: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    regime_trend_intensity_threshold: float
    regime_volatility_baseline_ratio: float
    regime_volatility_expansion_ratio: float
    regime_volatility_extreme_ratio: float
    regime_volume_breakout_threshold: float
    regime_long_short_imbalance_ratio: float
    regime_poc_gravity_atr_distance: float
    regime_vacuum_risk_score: float
    regime_wick_skewness_exhaustion: float
    regime_trend_intensity_strong: float
    regime_min_rr_ranging: float
    regime_min_rr_trending: float
    regime_volume_baseline_ratio: float
    regime_squeeze_threshold: float
    regime_breakout_buffer_atr: float

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "StrategistConfig":
        """Factory method to extract strategist config from the global config dict."""
        strat = full_config['strategist']
        return cls(
            model=str(strat['model']),
            role_prompt_path=os.path.join(resolve_project_root(), strat['role_definition_prompt']),
            model_temperature_draft=float(strat['model_temperature_draft']),
            model_temperature_synthesis=float(strat['model_temperature_synthesis']),
            min_trade_velocity=float(strat['min_trade_velocity']),
            stop_loss_buffer_min=float(strat['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(strat['stop_loss_buffer_max']),
            strategy_intent=str(full_config['strategy_intent']),
            macro_interval=str(full_config['observer']['macro_analysis_context']['time_interval']),
            micro_interval=str(full_config['observer']['micro_analysis_context']['time_interval']),
            regime_trend_intensity_threshold=float(full_config['observer']['regime_trend_intensity_threshold']),
            regime_volatility_baseline_ratio=float(full_config['observer']['regime_volatility_baseline_ratio']),
            regime_volatility_expansion_ratio=float(full_config['observer']['regime_volatility_expansion_ratio']),
            regime_volatility_extreme_ratio=float(full_config['observer']['regime_volatility_extreme_ratio']),
            regime_volume_breakout_threshold=float(full_config['observer']['regime_volume_breakout_threshold']),
            regime_long_short_imbalance_ratio=float(full_config['observer']['regime_long_short_imbalance_ratio']),
            regime_poc_gravity_atr_distance=float(full_config['observer']['regime_poc_gravity_atr_distance']),
            regime_vacuum_risk_score=float(full_config['observer']['regime_vacuum_risk_score']),
            regime_wick_skewness_exhaustion=float(full_config['observer']['regime_wick_skewness_exhaustion']),
            regime_trend_intensity_strong=float(full_config['observer']['regime_trend_intensity_strong']),
            regime_min_rr_ranging=float(full_config['observer']['regime_min_rr_ranging']),
            regime_min_rr_trending=float(full_config['observer']['regime_min_rr_trending']),
            regime_volume_baseline_ratio=float(full_config['observer']['regime_volume_baseline_ratio']),
            regime_squeeze_threshold=float(full_config['observer']['regime_squeeze_threshold']),
            regime_breakout_buffer_atr=float(full_config['observer']['regime_breakout_buffer_atr'])
        )

class StrategistAgent(BaseAgent):
    """
    The Strategist & Decision Engine.
    
    This agent coordinates the reasoning triad:
    1. PHASE A (DRAFTING): Transforms raw terminal telemetry into an initial 
       strategic execution plan (Limit Entry, TP, SL).
    2. PHASE B (SYNTHESIS): Absorbs adversarial feedback from the Critic 
       to harden the plan, applying 'Deep Limit Entry' (DLE) mitigations 
       where structural risks are identified.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Strategist with dual-temperature configuration.
        """
        self.config = StrategistConfig.from_dict(config_dict)
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature_draft,
            api_key=api_key,
            ai_client=ai_client
        )

    def draft(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase A: DRAFTING - Generates an initial strategic draft.
        
        This phase focuses on structural mapping and execution engineering.
        The prompt is signaled to enter Phase A by passing 'null' for draft/critique.
        """
        prompt = self._build_prompt(observation)
        logger.info("Strategist: Executing PHASE A: DRAFTING (Initial strategic plan)...")
        return self._execute_ai_cycle(
            prompt, 
            temperature=self.config.model_temperature_draft, 
            agent_name="Strategist"
        )

    def synthesize(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase B: SYNTHESIS - Crystalizes the draft and audit into a final decision.
        
        This phase focuses on risk absorption and confidence calibration.
        The prompt is signaled to enter Phase B by passing populated draft/critique context.
        """
        prompt = self._build_prompt(
            observation, 
            draft_plan=draft_plan, 
            critic_feedback=critique
        )
        logger.info("Strategist: Executing PHASE B: SYNTHESIS (Final strategy)...")
        return self._execute_ai_cycle(
            prompt, 
            temperature=self.config.model_temperature_synthesis, 
            agent_name="Strategist"
        )

    def _build_prompt(self, observation: Dict[str, Any], **extra_context) -> str:
        """
        Standardizes the context injection for both Drafting and Synthesis phases.
        
        Uses explicit 'null' strings for Phase A signaling, ensuring the LLM 
        processes the correct operational protocols in the template.
        """
        # Load the velocity floor for temporal calculations
        velocity_floor = self.config.min_trade_velocity
        
        # Calculate macro_hours for consistent temporal projection
        macro_hours = get_interval_seconds(self.config.macro_interval) / 3600

        # Prepare context (json.dumps handles None as 'null' automatically)
        context = {
            "observation_json": json.dumps(observation, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(extra_context.get("draft_plan"), indent=2, ensure_ascii=False),
            "critic_feedback": json.dumps(extra_context.get("critic_feedback"), indent=2, ensure_ascii=False),
            "min_trade_velocity": velocity_floor,
            "macro_hours": f"{macro_hours:.4f}",
            "stop_loss_buffer_min": self.config.stop_loss_buffer_min,
            "stop_loss_buffer_max": self.config.stop_loss_buffer_max,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "regime_trend_intensity_threshold": self.config.regime_trend_intensity_threshold,
            "regime_volatility_baseline_ratio": self.config.regime_volatility_baseline_ratio,
            "regime_volatility_expansion_ratio": self.config.regime_volatility_expansion_ratio,
            "regime_volatility_extreme_ratio": self.config.regime_volatility_extreme_ratio,
            "regime_volume_breakout_threshold": self.config.regime_volume_breakout_threshold,
            "regime_long_short_imbalance_ratio": self.config.regime_long_short_imbalance_ratio,
            "regime_poc_gravity_atr_distance": self.config.regime_poc_gravity_atr_distance,
            "regime_vacuum_risk_score": self.config.regime_vacuum_risk_score,
            "regime_wick_skewness_exhaustion": self.config.regime_wick_skewness_exhaustion,
            "regime_trend_intensity_strong": self.config.regime_trend_intensity_strong,
            "regime_min_rr_ranging": self.config.regime_min_rr_ranging,
            "regime_min_rr_trending": self.config.regime_min_rr_trending,
            "regime_volume_baseline_ratio": self.config.regime_volume_baseline_ratio,
            "regime_squeeze_threshold": self.config.regime_squeeze_threshold,
            "regime_breakout_buffer_atr": self.config.regime_breakout_buffer_atr
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
