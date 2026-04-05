import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# Initialize critic-specific logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig(AgentConfig):
    """Encapsulates risk-centric configuration for the CriticAgent.
    
    Attributes:
        threshold_skepticism_clear: Score threshold below which a plan is considered 'hardened'.
        threshold_skepticism_weak: Score threshold for minor concerns.
        threshold_skepticism_constructive: Score threshold for major logical gaps.
        structural_buffer_atr: Safe ATR-distance for stop-loss shielding behind structures.
        min_trade_velocity: Minimum required trade speed for directional validation.
    """
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
    vol_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    poc_gravity_atr_distance: float
    vacuum_risk_score: float
    wick_skewness_exhaustion: float
    wick_skewness_momentum_bullish: float
    wick_skewness_momentum_bearish: float
    trend_intensity_strong: float
    min_rr_ranging: float
    min_rr_trending: float
    min_vol_participation_ratio: float
    squeeze_threshold: float
    squeeze_audit_threshold: float
    threshold_skepticism_clear: int
    threshold_skepticism_weak: int
    threshold_skepticism_constructive: int
    anchor_drift_threshold: float
    min_trade_velocity: float
    structural_buffer_atr: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    structural_proximity_threshold: float
    gravity_volume_override_ratio: float
    holding_friction_dead_water: float
    holding_friction_highway: float
    holding_friction_climax: float
    holding_friction_standard: float
    missed_opportunity_atr_threshold: float
    mae_stress_thresholds: Dict[str, float]
    volume_profile_value_area_width: float
    vol_profile_width_ratio: float
    instruction_literal: Optional[str] = None

    @classmethod
    def from_dict(cls, cfg_dict: Dict[str, Any], instruction_literal: Optional[str] = None) -> "CriticConfig":
        """Factory method to assemble a CriticConfig from the global strategy configuration."""
        bs = cfg_dict['binary_star']
        critic_cfg = bs['critic']
        session_node = bs['session']
        regime = cfg_dict['regime_parameters']
        sampling = cfg_dict['analysis_window']
        audit = cfg_dict['audit_review']
        topography = cfg_dict['topography_parameters']
        visuals = cfg_dict['visuals']
        
        return cls(
            model=str(bs['model']),
            instruction_path=os.path.join(resolve_project_root(), critic_cfg['role_definition_prompt']),
            model_temperature=float(critic_cfg['model_temperature']),
            max_tool_iterations=int(cfg_dict['network']['gemini']['max_tool_iterations']),
            min_trade_velocity=float(session_node['min_trade_velocity']),
            stop_loss_buffer_min=float(session_node['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(session_node['stop_loss_buffer_max']),
            strategy_intent=str(cfg_dict.get('strategy_intent', "")),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            order_flow_lookback_hours=float(sampling['order_flow_lookback_hours']),
            trend_intensity_threshold=float(regime['trend_intensity_threshold']),
            volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            volatility_expansion_ratio=float(regime['volatility_expansion_ratio']),
            volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            vol_surge_vs_ma_ratio=float(regime['vol_surge_vs_ma_ratio']),
            long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            vacuum_risk_score=float(regime['vacuum_risk_score']),
            wick_skewness_exhaustion=float(regime['wick_skewness_exhaustion']),
            wick_skewness_momentum_bullish=float(regime['wick_skewness_momentum_bullish']),
            wick_skewness_momentum_bearish=float(regime['wick_skewness_momentum_bearish']),
            trend_intensity_strong=float(regime['trend_intensity_strong']),
            min_rr_ranging=float(regime['min_rr_ranging']),
            min_rr_trending=float(regime['min_rr_trending']),
            min_vol_participation_ratio=float(regime['min_vol_participation_ratio']),
            squeeze_threshold=float(regime['squeeze_threshold']),
            squeeze_audit_threshold=float(regime['squeeze_audit_threshold']),
            threshold_skepticism_clear=int(critic_cfg['threshold_skepticism_clear']),
            threshold_skepticism_weak=int(critic_cfg['threshold_skepticism_weak']),
            threshold_skepticism_constructive=int(critic_cfg['threshold_skepticism_constructive']),
            anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            structural_buffer_atr=float(regime['structural_buffer_atr']),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold']),
            cvd_intensity_extreme=float(regime['cvd_intensity_extreme']),
            funding_extreme_threshold=float(regime['funding_extreme_threshold']),
            structural_proximity_threshold=float(regime['structural_proximity_threshold']),
            gravity_volume_override_ratio=float(regime['gravity_volume_override_ratio']),
            holding_friction_dead_water=float(session_node['holding_friction_dead_water']),
            holding_friction_highway=float(session_node['holding_friction_highway']),
            holding_friction_climax=float(session_node['holding_friction_climax']),
            holding_friction_standard=float(session_node['holding_friction_standard']),
            missed_opportunity_atr_threshold=float(audit['missed_opportunity_atr_threshold']),
            mae_stress_thresholds={str(k): float(v) for k, v in audit['mae_stress_thresholds'].items()},
            volume_profile_value_area_width=float(topography['volume_profile_value_area_width']),
            vol_profile_width_ratio=float(visuals['vol_profile_width_ratio']),
            instruction_literal=instruction_literal
        )

class CriticAgent(BaseAgent):
    """Acts as the adversarial counterpart to the SessionAgent.
    Standardized to identify logical lapses, directional bias, and geometric
    violations in trade proposals by contrasting them against Math Truth.
    作为“控方”，其唯一任务是寻找提案中的漏洞。它不负责寻找机会，只负责“否定性审计”。
    """
    
    def __init__(
        self, 
        config: CriticConfig, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: genai.Client
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

    def evaluate(
        self, 
        observation: Optional[Dict[str, Any]], 
        last_plan: Dict[str, Any], 
        symbol: str, 
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_id: Optional[str] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Evaluates the proposed plan against physical market topography 
        and the mandatory CRITIC_CODES table. This is a cold, 
        deterministic audit designed to identify structural traps.
        质疑分数 (Skepticism Score) 反映了计划的风险程度：分数越高，漏洞越多。
        只有质疑分数低于阈值，计划才会被认为是“硬化”成功的。
        """
        logger.info(f"CriticAgent: Auditing {symbol} proposal for hidden risks...")
        try:
            context = self._build_context(
                observation, 
                last_plan, 
                debate_history=debate_history,
                math_fact_check=math_fact_check, 
                cache_id=cache_id
            )
            # 注入物理真理 (Math Fact Check) 作为审计的绝对底线
            prompt = self._prepare_prompt(self.config.instruction_path, **context)
            
            # 使用“冷温度”(Temp 0.2) 执行审计，确保逻辑的严谨性和确定性
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Critic: Critical failure during evaluation of {symbol}: {e}")
            raise

    def _build_context(
        self, 
        observation: Optional[Dict[str, Any]], 
        last_plan: Dict[str, Any], 
        debate_history: Optional[List[Dict[str, Any]]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Internal logic for constructing the adversarial audit context."""
        if cache_id:
            observation_json = "[CONTEXT_PROVIDED_VIA_GEMINI_CACHE]"
        elif observation:
            observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        else:
            raise ValueError("Critic: Audit attempted without baseline telemetry.")

        return {
            "observation_json": observation_json,
            "strategy_intent": self.config.strategy_intent,
            "last_plan": json.dumps(last_plan, indent=2, ensure_ascii=False),
            "debate_history_json": json.dumps(debate_history, indent=2, ensure_ascii=False) if debate_history else "null",
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "{}",
            "min_trade_velocity": self.config.min_trade_velocity,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "trend_intensity_threshold": self.config.trend_intensity_threshold,
            "volatility_baseline_ratio": self.config.volatility_baseline_ratio,
            "volatility_expansion_ratio": self.config.volatility_expansion_ratio,
            "volatility_extreme_ratio": self.config.volatility_extreme_ratio,
            "vol_surge_vs_ma_ratio": self.config.vol_surge_vs_ma_ratio,
            "long_short_imbalance_ratio": self.config.long_short_imbalance_ratio,
            "poc_gravity_atr_distance": self.config.poc_gravity_atr_distance,
            "vacuum_risk_score": self.config.vacuum_risk_score,
            "wick_skewness_exhaustion": self.config.wick_skewness_exhaustion,
            "wick_skewness_momentum_bullish": self.config.wick_skewness_momentum_bullish,
            "wick_skewness_momentum_bearish": self.config.wick_skewness_momentum_bearish,
            "trend_intensity_strong": self.config.trend_intensity_strong,
            "min_rr_ranging": self.config.min_rr_ranging,
            "min_rr_trending": self.config.min_rr_trending,
            "min_vol_participation_ratio": self.config.min_vol_participation_ratio,
            "squeeze_threshold": self.config.squeeze_threshold,
            "squeeze_audit_threshold": self.config.squeeze_audit_threshold,
            "threshold_skepticism_clear": self.config.threshold_skepticism_clear,
            "threshold_skepticism_weak": self.config.threshold_skepticism_weak,
            "threshold_skepticism_constructive": self.config.threshold_skepticism_constructive,
            "anchor_drift_threshold": self.config.anchor_drift_threshold,
            "structural_buffer_atr": self.config.structural_buffer_atr,
            "cvd_intensity_threshold": self.config.cvd_intensity_threshold,
            "cvd_intensity_extreme": self.config.cvd_intensity_extreme,
            "funding_extreme_threshold": self.config.funding_extreme_threshold,
            "structural_proximity_threshold": self.config.structural_proximity_threshold,
            "gravity_volume_override_ratio": self.config.gravity_volume_override_ratio
        }

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
                             trend_intensity: float, volatility_ratio: float, 
                             macro_interval_minutes: int) -> Dict[str, Any]:
        """[TOOL] Estimates trade duration based on market velocity floors with dynamic modifier v3.0."""
        from src.utils.math_utils import MathTools
        return MathTools.project_holding_time(
            entry=entry, take_profit=take_profit, atr=atr, 
            trend_intensity=trend_intensity, volatility_ratio=volatility_ratio,
            interval_minutes=macro_interval_minutes, min_velocity_floor=self.config.min_trade_velocity,
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
