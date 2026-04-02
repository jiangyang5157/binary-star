import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Union
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.pipeline_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig(AgentConfig):
    """Encapsulates configuration for the CriticAgent."""
    stop_loss_buffer_min: float
    stop_loss_buffer_max: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    order_flow_lookback_hours: float
    trend_intensity_threshold: float
    volatility_baseline_ratio: float
    volatility_expansion_ratio: float
    volatility_extreme_ratio: float
    volume_breakout_threshold: float
    long_short_imbalance_ratio: float
    poc_gravity_atr_distance: float
    vacuum_risk_score: float
    wick_skewness_exhaustion: float
    wick_skewness_momentum_bullish: float
    wick_skewness_momentum_bearish: float
    trend_intensity_strong: float
    min_rr_ranging: float
    min_rr_trending: float
    volume_baseline_ratio: float
    squeeze_threshold: float
    squeeze_audit_threshold: float
    threshold_skepticism_clear: int
    threshold_skepticism_weak: int
    threshold_skepticism_constructive: int
    anchor_drift_threshold: float
    min_trade_velocity: float

    @classmethod
    def from_dict(cls, cfg_dict: Dict[str, Any]) -> "CriticConfig":
        """Factory method to extract critic config from the global config dict."""
        bs = cfg_dict['binary_star']
        critic = bs['critic']
        session_node = bs['session']
        regime = cfg_dict['regime_parameters']
        shared = cfg_dict.get('agent_model_shared_config', {})
        sampling = cfg_dict['analysis_window']
        
        return cls(
            model=str(bs['model']),
            role_prompt_path=os.path.join(resolve_project_root(), critic['role_definition_prompt']),
            model_temperature=float(critic['model_temperature']),
            min_trade_velocity=float(session_node.get('min_trade_velocity', 0.5)),
            stop_loss_buffer_min=float(session_node['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(session_node['stop_loss_buffer_max']),
            strategy_intent=str(cfg_dict['strategy_intent']),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            order_flow_lookback_hours=float(sampling['order_flow_lookback_hours']),
            trend_intensity_threshold=float(regime['trend_intensity_threshold']),
            volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            volatility_expansion_ratio=float(regime['volatility_expansion_ratio']),
            volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            volume_breakout_threshold=float(regime['volume_breakout_threshold']),
            long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            vacuum_risk_score=float(regime['vacuum_risk_score']),
            wick_skewness_exhaustion=float(regime['wick_skewness_exhaustion']),
            wick_skewness_momentum_bullish=float(regime['wick_skewness_momentum_bullish']),
            wick_skewness_momentum_bearish=float(regime['wick_skewness_momentum_bearish']),
            trend_intensity_strong=float(regime['trend_intensity_strong']),
            min_rr_ranging=float(regime['min_rr_ranging']),
            min_rr_trending=float(regime['min_rr_trending']),
            volume_baseline_ratio=float(regime['volume_baseline_ratio']),
            squeeze_threshold=float(regime['squeeze_threshold']),
            squeeze_audit_threshold=float(regime['squeeze_audit_threshold']),
            threshold_skepticism_clear=int(critic['threshold_skepticism_clear']),
            threshold_skepticism_weak=int(critic['threshold_skepticism_weak']),
            threshold_skepticism_constructive=int(critic['threshold_skepticism_constructive']),
            anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            max_tool_iterations=int(shared.get('max_tool_iterations', 5))
        )

class CriticAgent(BaseAgent):
    """
    The Skeptical Risk Critic (Adversarial Agent).
    
    This agent performs a high-fidelity stress test on the Session draft.
    It identifies hidden flaws, structural traps, and math violations by 
    contrasting the draft against 'Math Fact Check' telemetry and volume topography.
    """
    def __init__(
        self, 
        config: CriticConfig, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: genai.Client,
        model: Optional[str] = None
    ):
        """
        Initializes the Critic with a pre-assembled type-safe configuration.
        """
        self.config = config
        super().__init__(
            config=self.config,
            ai_client=ai_client,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max
        )

    def evaluate(
        self, 
        observation: Optional[Dict[str, Any]], 
        draft_plan: Dict[str, Any], 
        symbol: str, 
        cache_id: Optional[str] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Unified adversarial audit method (The Phase 2 Challenge).
        Supports both Truth Bus (Cache) and Debug (Direct JSON) modes.
        """
        try:
            # Construct context with Truth Bus Matrix safety
            context = self._build_context(observation, draft_plan, math_fact_check=math_fact_check, cache_id=cache_id)
            prompt = self._prepare_prompt(self.config.role_prompt_path, **context)
            
            logger.info(f"Critic: Evaluating thesis for {symbol} (Truth Bus: {'ACTIVE' if cache_id else 'Direct'})")
            
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Critic: Evaluation failed for {symbol}: {e}")
            raise

    def _build_context(
        self, 
        observation: Optional[Dict[str, Any]], 
        draft_plan: Dict[str, Any], 
        math_fact_check: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Constructs the auditing context using the Truth Bus Decision Matrix:
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
            # Safety Fuse: Prevent evaluation without topographic data
            raise ValueError("Critic: Zero-Knowledge State. Neither observation nor cache_id provided.")

        return {
            "observation_json": observation_json,
            "draft_plan": json.dumps(draft_plan, indent=2, ensure_ascii=False),
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "",
            "min_trade_velocity": self.config.min_trade_velocity,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "trend_intensity_threshold": self.config.trend_intensity_threshold,
            "volatility_baseline_ratio": self.config.volatility_baseline_ratio,
            "volatility_expansion_ratio": self.config.volatility_expansion_ratio,
            "volatility_extreme_ratio": self.config.volatility_extreme_ratio,
            "volume_breakout_threshold": self.config.volume_breakout_threshold,
            "long_short_imbalance_ratio": self.config.long_short_imbalance_ratio,
            "poc_gravity_atr_distance": self.config.poc_gravity_atr_distance,
            "vacuum_risk_score": self.config.vacuum_risk_score,
            "wick_skewness_exhaustion": self.config.wick_skewness_exhaustion,
            "wick_skewness_momentum_bullish": self.config.wick_skewness_momentum_bullish,
            "wick_skewness_momentum_bearish": self.config.wick_skewness_momentum_bearish,
            "trend_intensity_strong": self.config.trend_intensity_strong,
            "min_rr_ranging": self.config.min_rr_ranging,
            "min_rr_trending": self.config.min_rr_trending,
            "volume_baseline_ratio": self.config.volume_baseline_ratio,
            "squeeze_threshold": self.config.squeeze_threshold,
            "squeeze_audit_threshold": self.config.squeeze_audit_threshold,
            "threshold_skepticism_clear": self.config.threshold_skepticism_clear,
            "threshold_skepticism_weak": self.config.threshold_skepticism_weak,
            "threshold_skepticism_constructive": self.config.threshold_skepticism_constructive,
            "anchor_drift_threshold": self.config.anchor_drift_threshold
        }

    # --- Tool Delegate Methods (for Function Calling) ---
    # We mirror these from SessionAgent so the Audit can also audit the math
    
    def calculate_risk_reward(self, entry: float, take_profit: float, stop_loss: float) -> Dict[str, Any]:
        from src.utils.math_utils import MathTools
        return MathTools.calculate_risk_reward(entry, take_profit, stop_loss)

    def calculate_atr_metrics(self, entry: float, stop_loss: float, take_profit: float, atr: float, current_price: Optional[float] = None) -> Dict[str, Any]:
        from src.utils.math_utils import MathTools
        return MathTools.calculate_atr_metrics(entry, stop_loss, take_profit, atr, current_price)

    def calculate_structural_proximity(self, stop_loss: float, atr: float, poc: Optional[float] = None, vah: Optional[float] = None, val: Optional[float] = None) -> Dict[str, Any]:
        from src.utils.math_utils import MathTools
        return MathTools.calculate_structural_proximity(stop_loss, atr, poc, vah, val)

    def project_holding_time(self, entry: float, take_profit: float, atr: float, 
                             trend_intensity: float, macro_interval_minutes: int) -> Dict[str, Any]:
        """[DELEGATE] Projects holding time using the config-driven velocity floor."""
        from src.utils.math_utils import MathTools
        return MathTools.project_holding_time(
            entry, take_profit, atr, trend_intensity, 
            macro_interval_minutes, self.config.min_trade_velocity
        )
