import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Union

from google import genai
from src.agent.base_agent import BaseAgent, AgentConfig
from src.utils.pipeline_utils import read_prompt_template, safe_format
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
        model_temperature_draft: Temperature for the initial thesis generation.
        model_temperature_synthesis: Lower temperature for final defensive hardening.
        min_trade_velocity: Minimum price speed (ATR/candle) required for entry.
        stop_loss_buffer_min: Minimum ATR distance for SL placement.
        strategy_intent: High-level tactical directive string.
        poc_gravity_atr_distance: Maximum distance from POC for gravity-based entry.
        vacuum_risk_score: Threshold for detecting liquidity gaps/vacuums.
    """
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
    breakout_buffer_atr: float
    breakout_frontrun_atr: float
    poc_magnet_atr_threshold: float
    gravity_volume_override_ratio: float
    boundary_clipping_atr: float
    holding_time_modifier: float
    participation_volume_threshold: float
    anchor_drift_threshold: float
    poc_confluence_strength: float
    structural_proximity_threshold: float
    balanced_atr_multiplier: float
    structural_buffer_atr: float
    cvd_intensity_threshold: float

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "SessionConfig":
        """Factory method to assemble a SessionConfig from the global YAML structure.
        
        Args:
            cfg: The unified dictionary from strategy_config.yaml.
            
        Returns:
            A populated SessionConfig instance.
        """
        bs = cfg['binary_star']
        strat = bs['session']
        regime = cfg['regime_parameters']
        sampling = cfg['analysis_window']
        shared = cfg.get('agent_model_shared_config', {})
        
        return cls(
            model=str(bs['model']),
            model_temperature=float(strat['model_temperature_draft']),
            role_prompt_path=os.path.join(resolve_project_root(), strat['role_definition_prompt']),
            max_tool_iterations=int(shared.get('max_tool_iterations', 5)),
            model_temperature_draft=float(strat['model_temperature_draft']),
            model_temperature_synthesis=float(strat['model_temperature_synthesis']),
            min_trade_velocity=float(strat['min_trade_velocity']),
            stop_loss_buffer_min=float(strat['stop_loss_buffer_min']),
            stop_loss_buffer_max=float(strat['stop_loss_buffer_max']),
            score_confidence_base=float(strat['score_confidence_base']),
            score_confidence_decay_min=float(strat['score_confidence_decay_min']),
            score_confidence_decay_max=float(strat['score_confidence_decay_max']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
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
            breakout_buffer_atr=float(regime['breakout_buffer_atr']),
            breakout_frontrun_atr=float(regime['breakout_frontrun_atr']),
            poc_magnet_atr_threshold=float(regime['poc_magnet_atr_threshold']),
            gravity_volume_override_ratio=float(regime['gravity_volume_override_ratio']),
            boundary_clipping_atr=float(regime['boundary_clipping_atr']),
            holding_time_modifier=float(strat['holding_time_modifier']),
            participation_volume_threshold=float(regime['participation_volume_threshold']),
            anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            poc_confluence_strength=float(regime['poc_confluence_strength']),
            structural_proximity_threshold=float(regime['structural_proximity_threshold']),
            balanced_atr_multiplier=float(regime['balanced_atr_multiplier']),
            structural_buffer_atr=float(regime['structural_buffer_atr']),
            cvd_intensity_threshold=float(regime['cvd_intensity_threshold'])
        )

class SessionAgent(BaseAgent):
    """The Session Analyst & Decision Engine.
    
    Responsible for transforming topographical telemetry into tactical trade blueprints.
    Operates in two primary phases:
    1. Drafting: Initial directional hypothesis and parameterization.
    2. Synthesis: Hardening the draft plan against Critic adversarial feedback.
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

    def draft(
        self, 
        observation: Optional[Dict[str, Any]], 
        symbol: str, 
        cache_id: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        critic_feedback: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executes Phase 1 (Drafting) of the reasoning cycle.
        
        Args:
            observation: Raw market telemetry (required if cache_id is None).
            symbol: Trading pair code.
            cache_id: Semantic context identifier for high-performance inference.
            tools: Native Python tool schemas definitions.
            critic_feedback: Optional rebuttal from a previous round for re-drafting.
            
        Returns:
            A reasoning draft containing 'opinion' and 'tactical_parameters'.
        """
        try:
            prompt = self._build_prompt(
                observation, 
                critic_feedback=critic_feedback, 
                cache_id=cache_id,
                current_phase="PHASE_A_DRAFTING"
            )
            logger.info(f"Session: Generating initial thesis for {symbol}...")
            
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature_draft,
                agent_name="Session_Draft",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Session: Critical failure during drafting for {symbol}: {e}")
            raise

    def synthesize(
        self, 
        draft_plan: Dict[str, Any], 
        critic_results: Dict[str, Any], 
        cache_id: Optional[str] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        observation: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Executes Phase 3 (Synthesis) for final plan hardening.
        
        Args:
            draft_plan: The Phase 1 output.
            critic_results: The adversarial audit results from the CriticAgent.
            cache_id: Context identifier.
            math_fact_check: Objective truth verification from Python utils.
            observation: Market topography (if no cache).
            tools: Tool definitions.
            
        Returns:
            The finalized, hardened trading decision.
        """
        try:
            prompt = self._build_prompt(
                observation, 
                draft_plan, 
                critic_results, 
                math_fact_check=math_fact_check, 
                cache_id=cache_id,
                current_phase="PHASE_B_SYNTHESIS"
            )
            logger.info(f"Session: Hardening decision against adversarial audit...")
            
            return self._execute_ai_cycle(
                payload=prompt, 
                temperature=self.config.model_temperature_synthesis,
                agent_name="Session_Synthesis",
                cached_content=cache_id,
                tools=tools
            )
        except Exception as e:
            logger.error(f"Session: Critical failure during synthesis: {e}")
            raise

    def _build_prompt(
        self, 
        observation: Optional[Dict[str, Any]], 
        draft_plan: Optional[Dict[str, Any]] = None,
        critic_feedback: Optional[Dict[str, Any]] = None,
        math_fact_check: Optional[Dict[str, Any]] = None,
        cache_id: Optional[str] = None,
        current_phase: str = "PHASE_A_DRAFTING"
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
            "current_phase": current_phase,
            "draft_plan_json": json.dumps(draft_plan, indent=2, ensure_ascii=False) if draft_plan else "{}",
            "critic_feedback": json.dumps(critic_feedback, indent=2, ensure_ascii=False) if critic_feedback else "{}",
            "math_fact_check": json.dumps(math_fact_check, indent=2, ensure_ascii=False) if math_fact_check else "{}",
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
            "breakout_buffer_atr": self.config.breakout_buffer_atr,
            "breakout_frontrun_atr": self.config.breakout_frontrun_atr,
            "poc_magnet_atr_threshold": self.config.poc_magnet_atr_threshold,
            "gravity_volume_override_ratio": self.config.gravity_volume_override_ratio,
            "boundary_clipping_atr": self.config.boundary_clipping_atr,
            "score_confidence_base": self.config.score_confidence_base,
            "score_confidence_decay_min": self.config.score_confidence_decay_min,
            "score_confidence_decay_max": self.config.score_confidence_decay_max,
            "holding_time_modifier": self.config.holding_time_modifier,
            "participation_volume_threshold": self.config.participation_volume_threshold,
            "anchor_drift_threshold": self.config.anchor_drift_threshold,
            "poc_confluence_strength": self.config.poc_confluence_strength,
            "structural_proximity_threshold": self.config.structural_proximity_threshold,
            "regime_balanced_atr_multiplier": self.config.balanced_atr_multiplier,
            "structural_buffer_atr": self.config.structural_buffer_atr,
            "cvd_intensity_threshold": self.config.cvd_intensity_threshold
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)

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
                             trend_intensity: float, macro_interval_minutes: int) -> Dict[str, Any]:
        """[TOOL] Estimates trade duration based on market velocity floors."""
        from src.utils.math_utils import MathTools
        return MathTools.project_holding_time(
            entry, take_profit, atr, trend_intensity, 
            macro_interval_minutes, self.config.min_trade_velocity
        )
