import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger
from src.utils.rate_limiter import CongestionController

# Initialize session-specific logger
logger = setup_logger(__name__, propagate=True)

@dataclass(frozen=True)
class SessionConfig(AgentConfig):
    """Encapsulates comprehensive strategic configuration for the SessionAgent.
    
    Attributes:
        min_trade_velocity: Minimum price speed (ATR/candle) required for entry.
        stop_loss_buffer_min: Minimum ATR distance for SL placement.
        volatility_baseline_ratio: Ratio above which regime shifts to 'Volatile'.
        poc_gravity_atr_distance: Maximum distance from POC for gravity entry.
        unit_atr_holding_hours: (Calculated) Estimated hours to clear 1 ATR in current regime.
        unit_atr_waiting_hours: (Calculated) Estimated hours to fill 1 ATR in current regime.
    """
    min_trade_velocity: float
    stop_loss_buffer_min: float
    strategy_intent: str
    macro_interval: str
    micro_interval: str
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
    breakout_frontrun_atr: float
    max_entry_distance_atr: float
    chaos_rr_discount: float
    volume_participation_threshold: float
    temporal_dilation_dead_water: float
    temporal_dilation_highway: float
    temporal_dilation_climax: float
    temporal_dilation_standard: float
    temporal_weight_dead_water: float
    temporal_weight_highway: float
    temporal_weight_climax: float
    temporal_weight_standard: float
    structural_proximity_threshold: float
    ranging_width_atr: float
    structural_buffer_atr: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    missed_opportunity_atr_threshold: float
    mae_threshold_pinpoint: float
    mae_threshold_standard: float
    mae_threshold_luck: float
    volume_profile_value_area_width: float
    volume_profile_width_ratio: float
    instruction_literal: Optional[str] = None

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any], instruction_literal: Optional[str] = None) -> "SessionConfig":
        """Factory method to assemble a SessionConfig from the global YAML structure.
        
        Args:
            cfg: The unified dictionary from strategy_config.yaml.
            
        Returns:
            A populated SessionConfig instance.
        """
        llm_cfg = cfg['llm']
        bs = cfg['binary_star']
        session_cfg = bs['session']
        regime = cfg['regime_parameters']
        sampling = cfg['analysis_window']
        audit = cfg['audit_review']
        topography = cfg['topography_parameters']
        visuals = cfg['visuals']
        
        active_provider = llm_cfg.get('active_provider')
        if not active_provider:
            raise ValueError("active_provider is not set in llm configuration.")
        active_provider = active_provider.lower()
        provider_cfg = llm_cfg.get(active_provider, {})
        model = provider_cfg.get('model')
        
        model_temperature = float(provider_cfg.get('session_temperature', 0.5))
        
        return cls(
            model=str(model),
            model_temperature=model_temperature,
            instruction_path=os.path.join(resolve_project_root(), llm_cfg['binary_star']['session_role_prompt']),
            max_tool_iterations=int(cfg['network']['gemini']['max_tool_iterations']),
            min_trade_velocity=float(session_cfg['min_trade_velocity']),
            stop_loss_buffer_min=float(session_cfg['stop_loss_buffer_min']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
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
            breakout_frontrun_atr=float(regime['breakout_frontrun_atr']),
            max_entry_distance_atr=float(regime['max_entry_distance_atr']),
            chaos_rr_discount=float(regime['chaos_rr_discount']),
            volume_participation_threshold=float(regime['volume_participation_threshold']),
            temporal_dilation_dead_water=float(session_cfg['temporal_dilation_dead_water']),
            temporal_dilation_highway=float(session_cfg['temporal_dilation_highway']),
            temporal_dilation_climax=float(session_cfg['temporal_dilation_climax']),
            temporal_dilation_standard=float(session_cfg['temporal_dilation_standard']),
            temporal_weight_dead_water=float(session_cfg['temporal_weight_dead_water']),
            temporal_weight_highway=float(session_cfg['temporal_weight_highway']),
            temporal_weight_climax=float(session_cfg['temporal_weight_climax']),
            temporal_weight_standard=float(session_cfg['temporal_weight_standard']),
            structural_proximity_threshold=float(regime['structural_proximity_threshold']),
            ranging_width_atr=float(regime['ranging_width_atr']),
            structural_buffer_atr=float(regime['structural_buffer_atr']),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold']),
            cvd_intensity_extreme=float(regime['cvd_intensity_extreme']),
            funding_extreme_threshold=float(regime['funding_extreme_threshold']),
            missed_opportunity_atr_threshold=float(audit['missed_opportunity_atr_threshold']),
            mae_threshold_pinpoint=float(audit['mae_threshold_pinpoint']),
            mae_threshold_standard=float(audit['mae_threshold_standard']),
            mae_threshold_luck=float(audit['mae_threshold_luck']),
            volume_profile_value_area_width=float(topography['volume_profile_value_area_width']),
            volume_profile_width_ratio=float(visuals['volume_profile']['width_ratio']),
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
        retry_max: int,
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

    def execute_session_cycle(
        self,
        observation: Optional[Dict[str, Any]],
        symbol: str,
        temperature: float,
        agent_name: str,
        debate_history: Optional[List[Dict[str, Any]]] = None,
        cache_id: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        visual_parts: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None
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
            
            payload = [prompt]
            if not cache_id and visual_parts:
                payload.extend(visual_parts)
                
            # 执行 AI 推理循环：支持 Gemini Cache 和 Function Calling (MathTools)
            return self._execute_ai_cycle(
                payload=payload, 
                temperature=temperature,
                agent_name=agent_name,
                cached_content=cache_id,
                tools=tools,
                system_instruction=system_instruction
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
            "strategy_intent": self.config.strategy_intent,
            "min_rr_ranging": self.config.min_rr_ranging,
            "min_rr_trending": self.config.min_rr_trending,
            "structural_buffer_atr": self.config.structural_buffer_atr,
            "poc_gravity_atr_distance": self.config.poc_gravity_atr_distance,
            "breakout_frontrun_atr": self.config.breakout_frontrun_atr,
            "max_entry_distance_atr": self.config.max_entry_distance_atr,
            "chaos_rr_discount": self.config.chaos_rr_discount
        }
        
        return self._prepare_prompt(self.config.instruction_path, **context)


