import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.datetime_utils import get_interval_minutes
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# Initialize session-specific logger
logger = setup_logger(__name__, propagate=True)

@dataclass(frozen=True)
class SessionConfig(AgentConfig):
    """Encapsulates comprehensive strategic configuration for the SessionAgent.
    
    This config merges high-level neural parameters with specific tactical thresholds
    defined in the global regime parameters.
    
    Attributes:
        min_trade_velocity: Minimum price speed (ATR/candle) required for entry.
        stop_loss_buffer_min: Minimum ATR distance for SL placement.
        strategy_intent: High-level tactical directive string.
        poc_gravity_atr_distance: Maximum distance from POC for gravity-based entry.
        vacuum_risk_score: Threshold for detecting liquidity gaps/vacuums.
    """
    min_trade_velocity: float
    stop_loss_buffer_min: float
    stop_loss_buffer_max: float
    score_confidence_base: float
    score_confidence_decay_min: float
    score_confidence_decay_max: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    trend_intensity_threshold: float
    volatility_baseline_ratio: float
    volatility_expansion_ratio: float
    volatility_extreme_ratio: float
    vol_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    short_heavy_imbalance_ratio: float
    poc_gravity_atr_distance: float
    vacuum_risk_score: float
    wick_skewness_exhaustion: float
    wick_skewness_momentum_bullish: float
    wick_skewness_momentum_bearish: float
    trend_intensity_strong: float
    trend_intensity_min_expansion: float
    min_rr_ranging: float
    min_rr_trending: float
    min_vol_participation_ratio: float
    squeeze_threshold: float
    breakout_buffer_atr: float
    breakout_frontrun_atr: float
    poc_magnet_atr_threshold: float
    gravity_volume_override_ratio: float
    noise_filter_atr_floor: float
    vol_participation_threshold: float
    holding_friction_dead_water: float
    holding_friction_highway: float
    holding_friction_climax: float
    holding_friction_standard: float
    anchor_drift_threshold: float
    poc_confluence_strength: float
    structural_proximity_threshold: float
    ranging_width_atr: float
    structural_buffer_atr: float
    cvd_intensity_threshold: float
    vol_profile_width_ratio: float
    missed_opportunity_atr_threshold: float
    mae_stress_thresholds: Dict[str, float]
    volume_profile_value_area_width: float
    instruction_literal: Optional[str] = None

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any], instruction_literal: Optional[str] = None) -> "SessionConfig":
        """Factory method to assemble a SessionConfig from the global YAML structure.
        
        Args:
            cfg: The unified dictionary from strategy_config.yaml.
            
        Returns:
            A populated SessionConfig instance.
        """
        bs = cfg['binary_star']
        session_cfg = bs['session']
        regime = cfg['regime_parameters']
        sampling = cfg['analysis_window']
        audit = cfg['audit_review']
        topography = cfg['topography_parameters']
        visuals = cfg['visuals']
        
        return cls(
            model=str(bs['model']),
            model_temperature=float(session_cfg['model_temperature']),
            instruction_path=os.path.join(resolve_project_root(), session_cfg['role_definition_prompt']),
            max_tool_iterations=int(cfg['network']['gemini']['max_tool_iterations']),
            min_trade_velocity=float(session_cfg['min_trade_velocity']),
            stop_loss_buffer_min=float(session_cfg['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(session_cfg['stop_loss_buffer_max']),
            score_confidence_base=float(session_cfg['score_confidence_base']),
            score_confidence_decay_min=float(session_cfg['score_confidence_decay_min']),
            score_confidence_decay_max=float(session_cfg['score_confidence_decay_max']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            trend_intensity_threshold=float(regime['trend_intensity_threshold']),
            volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            volatility_expansion_ratio=float(regime['volatility_expansion_ratio']),
            volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            vol_surge_vs_ma_ratio=float(regime['vol_surge_vs_ma_ratio']),
            long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            short_heavy_imbalance_ratio=float(regime['short_heavy_imbalance_ratio']),
            poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            vacuum_risk_score=float(regime['vacuum_risk_score']),
            wick_skewness_exhaustion=float(regime['wick_skewness_exhaustion']),
            wick_skewness_momentum_bullish=float(regime['wick_skewness_momentum_bullish']),
            wick_skewness_momentum_bearish=float(regime['wick_skewness_momentum_bearish']),
            trend_intensity_strong=float(regime['trend_intensity_strong']),
            trend_intensity_min_expansion=float(regime['trend_intensity_min_expansion']),
            min_rr_ranging=float(regime['min_rr_ranging']),
            min_rr_trending=float(regime['min_rr_trending']),
            min_vol_participation_ratio=float(regime['min_vol_participation_ratio']),
            squeeze_threshold=float(regime['squeeze_threshold']),
            breakout_buffer_atr=float(regime['breakout_buffer_atr']),
            breakout_frontrun_atr=float(regime['breakout_frontrun_atr']),
            poc_magnet_atr_threshold=float(regime['poc_magnet_atr_threshold']),
            gravity_volume_override_ratio=float(regime['gravity_volume_override_ratio']),
            noise_filter_atr_floor=float(regime['noise_filter_atr_floor']),
            vol_participation_threshold=float(regime['vol_participation_threshold']),
            holding_friction_dead_water=float(session_cfg['holding_friction_dead_water']),
            holding_friction_highway=float(session_cfg['holding_friction_highway']),
            holding_friction_climax=float(session_cfg['holding_friction_climax']),
            holding_friction_standard=float(session_cfg['holding_friction_standard']),
            anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            poc_confluence_strength=float(regime['poc_confluence_strength']),
            structural_proximity_threshold=float(regime['structural_proximity_threshold']),
            ranging_width_atr=float(regime['ranging_width_atr']),
            structural_buffer_atr=float(regime['structural_buffer_atr']),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold']),
            missed_opportunity_atr_threshold=float(audit['missed_opportunity_atr_threshold']),
            mae_stress_thresholds={str(k): float(v) for k, v in audit['mae_stress_thresholds'].items()},
            volume_profile_value_area_width=float(topography['volume_profile_value_area_width']),
            vol_profile_width_ratio=float(visuals['vol_profile_width_ratio']),
            instruction_literal=instruction_literal
        )

class SessionAgent(BaseAgent):
    """The Session Analyst & Decision Engine.
    
    Responsible for transforming topographical telemetry into tactical trade blueprints.
    Operates in an iterative cycle managed by the Orchestrator:
    1. Planning (Temp 0.7): Generates/Refines directional hypotheses and parameterization.
       在规划阶段，智能体具有较高的“创意性”，用于探索潜在的 Alpha 收益。
    2. Synthesis (Temp 0.3): Hardens the plan against Critic adversarial feedback in the final round.
       在合成阶段，智能体进入“冷逻辑”模式，强制对齐所有物理约束，确保生存。
    """
    
    def __init__(
        self, 
        config: SessionConfig, 
        ai_client: genai.Client,
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int
    ):
        """Standard constructor with dependency injection."""
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

    def execute_session_cycle(
        self,
        observation: Optional[Dict[str, Any]],
        symbol: str,
        temperature: float,
        agent_name: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_id: Optional[str] = None,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Core execution logic for a session reasoning step."""
        logger.info(f"SessionAgent: {agent_name} for {symbol}...")
        try:
            # 构建多模态提示词：整合物理事实、辩论历史与全局参数
            prompt = self._build_prompt(
                observation=observation, 
                debate_history=debate_history,
                cache_id=cache_id
            )
            
            # 执行 AI 推理循环：支持 Gemini Cache 和 Function Calling (MathTools)
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=temperature,
                agent_name=agent_name,
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Session: failure during {agent_name} for {symbol}: {e}")
            raise

    def _build_prompt(
        self, 
        observation: Optional[Dict[str, Any]], 
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_id: Optional[str] = None,
    ) -> str:
        """Internal logic for constructing the multimodal reasoning context.
        
        Orchestrates variable injection for both zero-knowledge (direct) 
        and high-context (cached) inference modes.
        """
        if cache_id:
            observation_json = "[CONTEXT_PROVIDED_VIA_GEMINI_CACHE]"
        elif observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Session: Reasoning attempted without market telemetry.")

        context = {
            "observation_json": observation_json,
            "debate_history_json": json.dumps(debate_history, indent=2, ensure_ascii=False) if debate_history else "null",
            "min_trade_velocity": self.config.min_trade_velocity,
            "stop_loss_buffer_min": self.config.stop_loss_buffer_min,
            "stop_loss_buffer_max": self.config.stop_loss_buffer_max,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "trend_intensity_threshold": self.config.trend_intensity_threshold,
            "volatility_baseline_ratio": self.config.volatility_baseline_ratio,
            "volatility_expansion_ratio": self.config.volatility_expansion_ratio,
            "volatility_extreme_ratio": self.config.volatility_extreme_ratio,
            "vol_surge_vs_ma_ratio": self.config.vol_surge_vs_ma_ratio,
            "long_short_imbalance_ratio": self.config.long_short_imbalance_ratio,
            "short_heavy_imbalance_ratio": self.config.short_heavy_imbalance_ratio,
            "poc_gravity_atr_distance": self.config.poc_gravity_atr_distance,
            "vacuum_risk_score": self.config.vacuum_risk_score,
            "wick_skewness_exhaustion": self.config.wick_skewness_exhaustion,
            "wick_skewness_momentum_bullish": self.config.wick_skewness_momentum_bullish,
            "wick_skewness_momentum_bearish": self.config.wick_skewness_momentum_bearish,
            "trend_intensity_strong": self.config.trend_intensity_strong,
            "trend_intensity_min_expansion": self.config.trend_intensity_min_expansion,
            "min_rr_ranging": self.config.min_rr_ranging,
            "min_rr_trending": self.config.min_rr_trending,
            "min_vol_participation_ratio": self.config.min_vol_participation_ratio,
            "squeeze_threshold": self.config.squeeze_threshold,
            "breakout_buffer_atr": self.config.breakout_buffer_atr,
            "breakout_frontrun_atr": self.config.breakout_frontrun_atr,
            "poc_magnet_atr_threshold": self.config.poc_magnet_atr_threshold,
            "gravity_volume_override_ratio": self.config.gravity_volume_override_ratio,
            "noise_filter_atr_floor": self.config.noise_filter_atr_floor,
            "score_confidence_base": self.config.score_confidence_base,
            "score_confidence_decay_min": self.config.score_confidence_decay_min,
            "score_confidence_decay_max": self.config.score_confidence_decay_max,
            "vol_participation_threshold": self.config.vol_participation_threshold,
            "macro_interval_minutes": get_interval_minutes(self.config.macro_interval),
            "micro_interval_minutes": get_interval_minutes(self.config.micro_interval),
            "anchor_drift_threshold": self.config.anchor_drift_threshold,
            "poc_confluence_strength": self.config.poc_confluence_strength,
            "structural_proximity_threshold": self.config.structural_proximity_threshold,
            "ranging_width_atr": self.config.ranging_width_atr,
            "structural_buffer_atr": self.config.structural_buffer_atr,
            "cvd_intensity_threshold": self.config.cvd_intensity_threshold,
            "holding_friction_dead_water": self.config.holding_friction_dead_water,
            "holding_friction_highway": self.config.holding_friction_highway,
            "holding_friction_climax": self.config.holding_friction_climax,
            "holding_friction_standard": self.config.holding_friction_standard
        }
        
        return self._prepare_prompt(self.config.instruction_path, **context)

    # --- Tool Delegates (Function Calling Interfaces) ---
    
    def calculate_risk_reward(self, entry: float, take_profit: float, stop_loss: float) -> Dict[str, Any]:
        """[TOOL] Calculates the Risk-Reward (RR) ratio for a trade geometry."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_risk_reward(entry, take_profit, stop_loss)

    def calculate_atr_metrics(self, entry: float, stop_loss: float, take_profit: float, atr: float, current_price: Optional[float] = None) -> Dict[str, Any]:
        """[TOOL] Standardizes trade distances using ATR (Average True Range)."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_atr_metrics(entry, stop_loss, take_profit, atr, current_price)

    def calculate_structural_proximity(self, stop_loss: float, atr: float, poc: Optional[float] = None, vah: Optional[float] = None, val: Optional[float] = None) -> Dict[str, Any]:
        """[TOOL] Measures isolation/shielding between SL and structural anchors (POC/VAH/VAL)."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_structural_proximity(stop_loss, atr, poc, vah, val)

    def project_holding_time(self, entry: float, take_profit: float, atr: float, 
                             trend_intensity: float, 
                             vol_expansion_ratio: float,
                             interval_minutes: int,
                             min_velocity_floor: Optional[float] = None) -> Dict[str, Any]:
        """[TOOL] Estimates trade duration based on market velocity floors with dynamic modifier v3.0."""
        from src.utils.math_utils import MathTools
        
        # Fallback to config if AI omits optional floor
        floor = min_velocity_floor if min_velocity_floor is not None else self.config.min_trade_velocity
        
        return MathTools.project_holding_time(
            entry=entry, take_profit=take_profit, atr=atr, 
            trend_intensity=trend_intensity, vol_expansion_ratio=vol_expansion_ratio,
            interval_minutes=interval_minutes, min_velocity_floor=floor,
            vr_base=self.config.volatility_baseline_ratio,
            vr_extreme=self.config.volatility_extreme_ratio,
            ti_strong=self.config.trend_intensity_strong,
            ti_thresh=self.config.trend_intensity_threshold,
            friction_dead_water=self.config.holding_friction_dead_water,
            friction_highway=self.config.holding_friction_highway,
            friction_climax=self.config.holding_friction_climax,
            friction_standard=self.config.holding_friction_standard
        )
    def calculate_opportunity_cost(self, missed_range: float, atr_macro: float) -> Dict[str, Any]:
        """[TOOL] Quantifies the 'Cost of Cowardice' (volatility missed during neutral stance)."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_opportunity_cost(
            missed_range, 
            atr_macro, 
            threshold=self.config.missed_opportunity_atr_threshold
        )

    def calculate_mae_stress(self, mae_distance: float, max_atr_used: float) -> Dict[str, Any]:
        """[TOOL] Evaluates the Maximum Adverse Excursion (MAE) stress against the move volatility."""
        from src.utils.math_utils import MathTools
        return MathTools.calculate_mae_stress(
            mae_distance, 
            max_atr_used, 
            thresholds=self.config.mae_stress_thresholds
        )
