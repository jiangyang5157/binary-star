import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig:
    """Encapsulates configuration for the CriticAgent."""
    model: str
    role_prompt_path: str
    model_temperature: float
    stop_loss_buffer_min: float
    stop_loss_buffer_max: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    order_flow_lookback_hours: float
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
    regime_squeeze_audit_threshold: float
    threshold_skepticism_clear: int
    threshold_skepticism_weak: int
    threshold_skepticism_constructive: int
    regime_trend_intensity_strong: float

    @classmethod
    def from_dict(cls, full_config: Dict[str, Any]) -> "CriticConfig":
        """Factory method to extract critic config from the global config dict."""
        critic = full_config['critic']
        strat = full_config['strategist']
        return cls(
            model=str(critic['model']),
            role_prompt_path=os.path.join(resolve_project_root(), critic['role_definition_prompt']),
            model_temperature=float(critic['model_temperature']),
            stop_loss_buffer_min=float(strat['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(strat['stop_loss_buffer_max']),
            strategy_intent=str(full_config['strategy_intent']),
            macro_interval=str(full_config['observer']['macro_analysis_context']['time_interval']),
            micro_interval=str(full_config['observer']['micro_analysis_context']['time_interval']),
            order_flow_lookback_hours=float(full_config['observer']['order_flow_lookback_hours']),
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
            regime_squeeze_audit_threshold=float(full_config['observer']['regime_squeeze_audit_threshold']),
            threshold_skepticism_clear=int(critic['threshold_skepticism_clear']),
            threshold_skepticism_weak=int(critic['threshold_skepticism_weak']),
            threshold_skepticism_constructive=int(critic['threshold_skepticism_constructive'])
        )

class CriticAgent(BaseAgent):
    """
    The Skeptical Risk Auditor (Adversarial Agent).
    
    This agent performs a high-fidelity stress test on the Strategist's draft.
    It identifies hidden flaws, structural traps, and math violations by 
    contrasting the draft against 'Math Fact Check' telemetry and volume topography.
    """
    def __init__(self, config_dict: Dict[str, Any], api_key: str, ai_client: Optional[genai.Client] = None):
        """
        Initializes the Critic with configuration.
        """
        self.config = CriticConfig.from_dict(config_dict)
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature,
            api_key=api_key,
            ai_client=ai_client
        )

    def audit(self, observation: Dict[str, Any], draft_plan: Dict[str, Any], math_fact_check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Performs an adversarial audit of a proposed trading draft.
        
        Args:
            observation: The forensic market map (Observer output).
            draft_plan: The proposed strategy from Strategist (Phase A).
            math_fact_check: Deterministic math facts (RR, ATR distances) to prevent LLM hallucination.
            
        Returns:
            A critique dictionary containing 'is_veto' status and risk tags (e.g., [CLEAR], [LIQUIDITY_VOID]).
        """
        # Prepare semantic context for the audit session
        context = {
            "observation_json": json.dumps(observation, indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(draft_plan, indent=2, ensure_ascii=False),
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "Not provided by system.",
            "stop_loss_buffer_min": self.config.stop_loss_buffer_min,
            "stop_loss_buffer_max": self.config.stop_loss_buffer_max,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "order_flow_lookback_hours": self.config.order_flow_lookback_hours,
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
            "regime_squeeze_audit_threshold": self.config.regime_squeeze_audit_threshold,
            "threshold_skepticism_clear": self.config.threshold_skepticism_clear,
            "threshold_skepticism_weak": self.config.threshold_skepticism_weak,
            "threshold_skepticism_constructive": self.config.threshold_skepticism_constructive
        }
        
        prompt = self._prepare_prompt(self.config.role_prompt_path, **context)
        
        logger.info("Critic: Performing adversarial audit...")
        return self._execute_ai_cycle(prompt, agent_name="Critic")
