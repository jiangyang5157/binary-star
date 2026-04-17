import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
from src.utils.rate_limiter import CongestionController

# Initialize critic-specific logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class CriticConfig(AgentConfig):
    """Encapsulates risk-centric configuration for the CriticAgent.
    
    Attributes:
        structural_buffer_atr: Safe ATR-distance for stop-loss shielding behind structures.
        min_trade_velocity: Minimum required trade speed for directional validation.
    """
    stop_loss_buffer_min: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
    cvd_micro_lookback_candles: int
    trend_intensity_threshold: float
    volatility_baseline_ratio: float
    volatility_extreme_ratio: float
    volume_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    short_heavy_imbalance_ratio: float
    poc_gravity_atr_distance: float
    vacuum_risk_score: float
    wick_skew_exhaustion: float
    trend_intensity_strong: float
    trend_intensity_min_expansion: float
    min_rr_ranging: float
    min_rr_trending: float
    min_volume_participation_ratio: float
    squeeze_threshold: float
    squeeze_audit_threshold: float
    min_trade_velocity: float
    structural_buffer_atr: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    structural_proximity_threshold: float
    temporal_dilation_dead_water: float
    temporal_dilation_highway: float
    temporal_dilation_climax: float
    temporal_dilation_standard: float
    temporal_weight_dead_water: float
    temporal_weight_highway: float
    temporal_weight_climax: float
    temporal_weight_standard: float
    missed_opportunity_atr_threshold: float
    mae_threshold_pinpoint: float
    mae_threshold_standard: float
    mae_threshold_luck: float
    volume_profile_value_area_width: float
    volume_profile_width_ratio: float
    max_holding_hours: float
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
            instruction_path=os.path.join(resolve_project_root(), cfg_dict['critic']['role_definition_prompt']),
            model_temperature=float(critic_cfg['model_temperature']),
            max_tool_iterations=int(cfg_dict['network']['gemini']['max_tool_iterations']),
            min_trade_velocity=float(session_node['min_trade_velocity']),
            stop_loss_buffer_min=float(session_node['stop_loss_buffer_min']),
            strategy_intent=str(cfg_dict.get('strategy_intent', "")),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            cvd_micro_lookback_candles=int(sampling['cvd_micro_lookback_candles']),
            trend_intensity_threshold=float(regime['trend_intensity_threshold']),
            volatility_baseline_ratio=float(regime['volatility_baseline_ratio']),
            volatility_extreme_ratio=float(regime['volatility_extreme_ratio']),
            volume_surge_vs_ma_ratio=float(regime['volume_surge_vs_ma_ratio']),
            long_short_imbalance_ratio=float(regime['long_short_imbalance_ratio']),
            short_heavy_imbalance_ratio=float(regime['short_heavy_imbalance_ratio']),
            poc_gravity_atr_distance=float(regime['poc_gravity_atr_distance']),
            vacuum_risk_score=float(regime['vacuum_risk_score']),
            wick_skew_exhaustion=float(regime['wick_skew_exhaustion']),
            trend_intensity_strong=float(regime['trend_intensity_strong']),
            trend_intensity_min_expansion=float(regime['trend_intensity_min_expansion']),
            min_rr_ranging=float(regime['min_rr_ranging']),
            min_rr_trending=float(regime['min_rr_trending']),
            min_volume_participation_ratio=float(regime['min_volume_participation_ratio']),
            squeeze_threshold=float(regime['squeeze_threshold']),
            squeeze_audit_threshold=float(regime['squeeze_audit_threshold']),
            structural_buffer_atr=float(regime['structural_buffer_atr']),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold']),
            cvd_intensity_extreme=float(regime['cvd_intensity_extreme']),
            funding_extreme_threshold=float(regime['funding_extreme_threshold']),
            structural_proximity_threshold=float(regime['structural_proximity_threshold']),
            temporal_dilation_dead_water=float(session_node['temporal_dilation_dead_water']),
            temporal_dilation_highway=float(session_node['temporal_dilation_highway']),
            temporal_dilation_climax=float(session_node['temporal_dilation_climax']),
            temporal_dilation_standard=float(session_node['temporal_dilation_standard']),
            temporal_weight_dead_water=float(session_node['temporal_weight_dead_water']),
            temporal_weight_highway=float(session_node['temporal_weight_highway']),
            temporal_weight_climax=float(session_node['temporal_weight_climax']),
            temporal_weight_standard=float(session_node['temporal_weight_standard']),
            missed_opportunity_atr_threshold=float(audit['missed_opportunity_atr_threshold']),
            mae_threshold_pinpoint=float(audit['mae_threshold_pinpoint']),
            mae_threshold_standard=float(audit['mae_threshold_standard']),
            mae_threshold_luck=float(audit['mae_threshold_luck']),
            volume_profile_value_area_width=float(topography['volume_profile_value_area_width']),
            volume_profile_width_ratio=float(visuals['volume_profile']['width_ratio']),
            max_holding_hours=float(session_node['max_holding_hours']),
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
        ai_client: genai.Client,
        congestion_controller: Optional[CongestionController] = None
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
            retry_max=retry_max,
            congestion_controller=congestion_controller
        )

    def evaluate(
        self, 
        observation: Optional[Dict[str, Any]], 
        last_plan: Dict[str, Any], 
        symbol: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_id: Optional[str] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        visual_parts: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates the proposed plan against physical market topography 
        and the mandatory CRITIC_CODES table. This is a cold, 
        deterministic audit designed to identify structural traps.
        """
        logger.info(f"CriticAgent: Auditing {symbol} proposal...")
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
            
            payload = [prompt]
            if not cache_id and visual_parts:
                payload.extend(visual_parts)
                
            # 使用“冷温度”(Temp 0.2) 执行审计，确保逻辑的严谨性和确定性
            return self._execute_ai_cycle(
                payload=payload, 
                temperature=self.config.model_temperature,
                agent_name="Critic_Evaluation",
                cached_content=cache_id,
                tools=tools,
                system_instruction=system_instruction
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
            "trend_intensity_threshold": self.config.trend_intensity_threshold,
            "volatility_baseline_ratio": self.config.volatility_baseline_ratio,
            "volatility_extreme_ratio": self.config.volatility_extreme_ratio,
            "long_short_imbalance_ratio": self.config.long_short_imbalance_ratio,
            "short_heavy_imbalance_ratio": self.config.short_heavy_imbalance_ratio,
            "poc_gravity_atr_distance": self.config.poc_gravity_atr_distance,
            "vacuum_risk_score": self.config.vacuum_risk_score,
            "trend_intensity_strong": self.config.trend_intensity_strong,
            "trend_intensity_min_expansion": self.config.trend_intensity_min_expansion,
            "min_rr_ranging": self.config.min_rr_ranging,
            "min_rr_trending": self.config.min_rr_trending,
            "min_volume_participation_ratio": self.config.min_volume_participation_ratio,
            "squeeze_threshold": self.config.squeeze_threshold,
            "squeeze_audit_threshold": self.config.squeeze_audit_threshold,
            "structural_buffer_atr": self.config.structural_buffer_atr,
            "cvd_intensity_threshold": self.config.cvd_intensity_threshold,
            "cvd_intensity_extreme": self.config.cvd_intensity_extreme,
            "funding_extreme_threshold": self.config.funding_extreme_threshold,
            "max_holding_hours": self.config.max_holding_hours,
            "temporal_dilation_dead_water": self.config.temporal_dilation_dead_water,
            "temporal_dilation_highway": self.config.temporal_dilation_highway,
            "temporal_dilation_climax": self.config.temporal_dilation_climax,
            "temporal_dilation_standard": self.config.temporal_dilation_standard
        }
