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
    score_confidence_base: float
    score_confidence_decay_min: float
    score_confidence_decay_max: float
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
    regime_wick_skewness_momentum_bullish: float
    regime_wick_skewness_momentum_bearish: float
    regime_trend_intensity_strong: float
    regime_min_rr_ranging: float
    regime_min_rr_trending: float
    regime_volume_baseline_ratio: float
    regime_squeeze_threshold: float
    regime_breakout_buffer_atr: float
    regime_breakout_frontrun_atr: float
    regime_poc_magnet_atr_threshold: float
    regime_gravity_volume_override_ratio: float
    regime_boundary_clipping_atr: float
    holding_time_modifier: float
    regime_participation_volume_threshold: float
    regime_anchor_drift_threshold: float
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, strategist_cfg: Dict[str, Any], observer_cfg: Dict[str, Any], strategy_intent: str, max_tool_iterations: int) -> "StrategistConfig":
        """Factory method to extract strategist config from injected components."""
        return cls(
            model=str(strategist_cfg['model']),
            role_prompt_path=os.path.join(resolve_project_root(), strategist_cfg['role_definition_prompt']),
            model_temperature_draft=float(strategist_cfg['model_temperature_draft']),
            model_temperature_synthesis=float(strategist_cfg['model_temperature_synthesis']),
            min_trade_velocity=float(strategist_cfg['min_trade_velocity']),
            stop_loss_buffer_min=float(strategist_cfg['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(strategist_cfg['stop_loss_buffer_max']),
            score_confidence_base=float(strategist_cfg['score_confidence_base']),
            score_confidence_decay_min=float(strategist_cfg['score_confidence_decay_min']),
            score_confidence_decay_max=float(strategist_cfg['score_confidence_decay_max']),
            strategy_intent=strategy_intent,
            macro_interval=str(observer_cfg['macro_analysis_context']['time_interval']),
            micro_interval=str(observer_cfg['micro_analysis_context']['time_interval']),
            regime_trend_intensity_threshold=float(observer_cfg['regime_trend_intensity_threshold']),
            regime_volatility_baseline_ratio=float(observer_cfg['regime_volatility_baseline_ratio']),
            regime_volatility_expansion_ratio=float(observer_cfg['regime_volatility_expansion_ratio']),
            regime_volatility_extreme_ratio=float(observer_cfg['regime_volatility_extreme_ratio']),
            regime_volume_breakout_threshold=float(observer_cfg['regime_volume_breakout_threshold']),
            regime_long_short_imbalance_ratio=float(observer_cfg['regime_long_short_imbalance_ratio']),
            regime_poc_gravity_atr_distance=float(observer_cfg['regime_poc_gravity_atr_distance']),
            regime_vacuum_risk_score=float(observer_cfg['regime_vacuum_risk_score']),
            regime_wick_skewness_exhaustion=float(observer_cfg['regime_wick_skewness_exhaustion']),
            regime_wick_skewness_momentum_bullish=float(observer_cfg['regime_wick_skewness_momentum_bullish']),
            regime_wick_skewness_momentum_bearish=float(observer_cfg['regime_wick_skewness_momentum_bearish']),
            regime_trend_intensity_strong=float(observer_cfg['regime_trend_intensity_strong']),
            regime_min_rr_ranging=float(observer_cfg['regime_min_rr_ranging']),
            regime_min_rr_trending=float(observer_cfg['regime_min_rr_trending']),
            regime_volume_baseline_ratio=float(observer_cfg['regime_volume_baseline_ratio']),
            regime_squeeze_threshold=float(observer_cfg['regime_squeeze_threshold']),
            regime_breakout_buffer_atr=float(observer_cfg['regime_breakout_buffer_atr']),
            regime_breakout_frontrun_atr=float(observer_cfg['regime_breakout_frontrun_atr']),
            regime_poc_magnet_atr_threshold=float(observer_cfg['regime_poc_magnet_atr_threshold']),
            regime_gravity_volume_override_ratio=float(observer_cfg['regime_gravity_volume_override_ratio']),
            regime_boundary_clipping_atr=float(observer_cfg['regime_boundary_clipping_atr']),
            holding_time_modifier=float(strategist_cfg['holding_time_modifier']),
            regime_participation_volume_threshold=float(observer_cfg['regime_participation_volume_threshold']),
            regime_anchor_drift_threshold=float(observer_cfg['regime_anchor_drift_threshold']),
            max_tool_iterations=max_tool_iterations
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
    def __init__(
        self, 
        config: StrategistConfig, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: genai.Client
    ):
        """
        Initializes the Strategist with a pre-assembled type-safe configuration.
        """
        self.config = config
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature_draft,
            ai_client=ai_client,
            max_tool_iterations=self.config.max_tool_iterations,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max
        )

    def draft(
        self, 
        observation: Optional[Dict[str, Any]], 
        symbol: str, 
        cache_id: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        previous_critique: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Unified drafting method (The Phase 1 Core).
        Supports both Truth Bus (Cache) and Debug (Direct JSON) modes.
        """
        try:
            prompt = self._build_prompt(observation, critic_feedback=previous_critique, cache_id=cache_id)
            logger.info(f"Strategist: Drafting thesis for {symbol} (Truth Bus: {'ACTIVE' if cache_id else 'Direct'})")
            
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature_draft,
                agent_name="Strategist_Draft",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Strategist: Drafting failed for {symbol}: {e}")
            raise

    def synthesize(
        self, 
        draft_plan: Dict[str, Any], 
        critique: Dict[str, Any], 
        cache_id: Optional[str] = None,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Unified synthesis method (The Phase 3 Hardening).
        Integrates adversarial feedback into the final decision.
        """
        try:
            # During synthesis, we typically rely on Cache for topographic data
            prompt = self._build_prompt(None, draft_plan, critique, cache_id=cache_id)
            logger.info(f"Strategist: Synthesizing final hardened decision (Truth Bus: {'ACTIVE' if cache_id else 'Direct'})")
            
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature_synthesis,
                agent_name="Strategist_Synthesis",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Strategist: Synthesis failed: {e}")
            raise

    def _build_prompt(
        self, 
        observation: Optional[Dict[str, Any]], 
        draft_plan: Optional[Dict[str, Any]] = None,
        critic_feedback: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None
    ) -> str:
        """
        Constructs the reasoning prompt using the Truth Bus Decision Matrix:
        1. Cache ID present -> Reference context, suppress JSON. (Production)
        2. Observation present -> Embed raw JSON. (Debug / Fallback)
        3. Both None -> Fuse / Raise ValueError. (Safety)
        """
        # --- The Truth Bus Matrix ---
        if cache_id:
            # Production: Optimization active. Refer to system context.
            observation_json = "[CONTEXT_PROVIDED_VIA_CACHE]"
        elif observation:
            # Debug/Fallback: Manual data injection.
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            # Safety Fuse: Prevent reasoning without topographic data
            raise ValueError("Strategist: Zero-Knowledge State. Neither observation nor cache_id provided.")

        context = {
            "observation_json": observation_json,
            "draft_plan_json": json.dumps(draft_plan, indent=2, ensure_ascii=False) if draft_plan else "{}",
            "critic_feedback_json": json.dumps(critic_feedback, indent=2, ensure_ascii=False) if critic_feedback else "{}",
            "min_trade_velocity": self.config.min_trade_velocity,
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
            "regime_wick_skewness_momentum_bullish": self.config.regime_wick_skewness_momentum_bullish,
            "regime_wick_skewness_momentum_bearish": self.config.regime_wick_skewness_momentum_bearish,
            "regime_trend_intensity_strong": self.config.regime_trend_intensity_strong,
            "regime_min_rr_ranging": self.config.regime_min_rr_ranging,
            "regime_min_rr_trending": self.config.regime_min_rr_trending,
            "regime_volume_baseline_ratio": self.config.regime_volume_baseline_ratio,
            "regime_squeeze_threshold": self.config.regime_squeeze_threshold,
            "regime_breakout_buffer_atr": self.config.regime_breakout_buffer_atr,
            "regime_breakout_frontrun_atr": self.config.regime_breakout_frontrun_atr,
            "regime_poc_magnet_atr_threshold": self.config.regime_poc_magnet_atr_threshold,
            "regime_gravity_volume_override_ratio": self.config.regime_gravity_volume_override_ratio,
            "regime_boundary_clipping_atr": self.config.regime_boundary_clipping_atr,
            "score_confidence_base": self.config.score_confidence_base,
            "score_confidence_decay_min": self.config.score_confidence_decay_min,
            "score_confidence_decay_max": self.config.score_confidence_decay_max,
            "holding_time_modifier": self.config.holding_time_modifier,
            "regime_participation_volume_threshold": self.config.regime_participation_volume_threshold,
            "regime_anchor_drift_threshold": self.config.regime_anchor_drift_threshold
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)

    # --- Tool Delegate Methods (for Function Calling) ---
    
    def calculate_risk_reward(self, entry: float, take_profit: float, stop_loss: float) -> Dict[str, Any]:
        from src.agent.tools.math_tools import MathTools
        return MathTools.calculate_risk_reward(entry, take_profit, stop_loss)

    def calculate_atr_metrics(self, entry: float, stop_loss: float, take_profit: float, atr: float, current_price: Optional[float] = None) -> Dict[str, Any]:
        from src.agent.tools.math_tools import MathTools
        return MathTools.calculate_atr_metrics(entry, stop_loss, take_profit, atr, current_price)

    def calculate_structural_proximity(self, stop_loss: float, atr: float, poc: Optional[float] = None, vah: Optional[float] = None, val: Optional[float] = None) -> Dict[str, Any]:
        from src.agent.tools.math_tools import MathTools
        return MathTools.calculate_structural_proximity(stop_loss, atr, poc, vah, val)

    def project_holding_time(self, entry: float, take_profit: float, atr: float, 
                             trend_intensity: float, macro_interval_minutes: int) -> Dict[str, Any]:
        """[DELEGATE] Projects holding time using the config-driven velocity floor."""
        from src.agent.tools.math_tools import MathTools
        return MathTools.project_holding_time(
            entry, take_profit, atr, trend_intensity, 
            macro_interval_minutes, self.config.min_trade_velocity
        )
