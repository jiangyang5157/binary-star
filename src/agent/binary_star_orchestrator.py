import json
import os
import logging
from typing import Dict, Any, List, Optional
from google.genai import types

from src.infrastructure.gemini.cache_manager import GeminiCacheManager
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.analyzer.math_fact_checker import MathFactChecker
from src.agent.debate_loop import DebateLoop
from src.agent.session_agent import SessionAgent, SessionConfig
from src.agent.critic_agent import CriticAgent, CriticConfig
from src.infrastructure.ai_factory import AIFactory
from src.utils.math_utils import MathTools
from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.utils.rate_limiter import CongestionController
from src.utils.pipeline_utils import load_config, get_file_hash, read_prompt_template, safe_format
from src.utils.datetime_utils import parse_iso_to_utc, FILE_TIMESTAMP_FORMAT, get_interval_minutes
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# Initialize standard hardened logger for orchestrator telemetry
logger = setup_logger(__name__)

class BinaryStarOrchestrator:
    """The central neurological hub for the adversarial reasoning pipeline.
    
    The Orchestrator implements the 'Binary Star' protocol, where the logic is
    standardized into a high-context debate between a Session Analyst (Thesis)
    and an Audit Critic (Antithesis).
    
    Key Innovations:
    1. Truth Bus (Shared Cache): Multimodal market topography is cached once and
       shared across the reasoning triad to eliminate context drift and cost.
    2. Physical Verification: AI proposals are cross-referenced against Python-native
       math fact-checks to prevent hallucination in trade geometry.
    3. Adversarial Hardening: Iterative debate rounds ensure the final trade
       blueprint is logically sound and structurally shielded.
    """
    obs_config: MarketObserverConfig
    session_config: SessionConfig
    critic_config: CriticConfig

    def __init__(self, 
                 config_dict: Dict[str, Any], 
                 api_key: str, 
                 data_root: str,
                 symbol: str,
                 instruction_overrides: Optional[Dict[str, str]] = None,
                 exchange_client: Optional[AbstractExchangeClient] = None):
        """Initializes the orchestrator as a central resource and configuration hub.
        
        Args:
            config_dict: The global strategy configuration (strategy_config.yaml).
            api_key: Authenticated Google GenAI API key.
            data_root: Logical root directory for forensic asset persistence.
            instruction_overrides: In-memory mapping of agent names to logic templates.
        """
        self.config = config_dict
        self.api_key = api_key
        self.data_root = data_root
        self.symbol = symbol
        self.instruction_overrides = instruction_overrides or {}
        
        # 0. Global Configuration Merging (Physical Split maintained for Snapshot Purity)
        self.global_config = load_config('config/global_config.yaml')
        
        # 0. Forensic Logging Initialization (Standardized v5.10 Telemetry)
        # Always enable file logging for forensic audit trails (Reverted v6.50)
        session_log_path = os.path.join(resolve_project_root(), self.data_root, "session.log")
        setup_logger("src", log_level=logging.INFO, log_file=session_log_path,
                     max_bytes=10 * 1024 * 1024, backup_count=5)  # 10MB x 5 = 50MB max
        logger.info(f"--- Binary Star Session Activated: {self.data_root} ---")
        
        # 1. Shared Infrastructure Clients (Dynamic Provider Selection)
        self.client = AIFactory.create_client(api_key=api_key, config_dict=self.global_config)

        self.exchange_client: AbstractExchangeClient = exchange_client or BinanceFuturesClient()
        
        # 2. Global Environment Constants (Resolved from Global Config)
        gemini_net = self.global_config['network']['gemini']
        self.api_timeout = int(gemini_net['api_timeout_seconds'])
        self.retry_count = int(gemini_net['retry_count'])
        self.max_tool_iterations = int(gemini_net['max_tool_iterations'])
        
        retry_strategy = gemini_net['retry_strategy']
        self.retry_multiplier = float(retry_strategy['multiplier'])
        self.retry_min = int(retry_strategy['min_seconds'])
        self.retry_max = int(retry_strategy['max_seconds'])

        # 3. Binary Star Protocol Parameters (Neural Infrastructure)
        self.llm_bs_config = self.global_config['llm']['binary_star']
        self.max_rounds = int(self.llm_bs_config['max_rounds'])
        
        # v14.0: Resolve shared model from active provider (decoupled from binary_star node)
        active_llm_cfg = self.global_config['llm']
        active_provider = active_llm_cfg.get('active_provider')
        if not active_provider:
            raise ValueError("active_provider is not set in llm configuration.")
        active_provider = active_provider.lower()
        active_provider_cfg = active_llm_cfg.get(active_provider, {})
        self.shared_model = active_provider_cfg.get('model')
        
        # Context Cache Config — read from active provider (only Gemini enables caching)
        cache_cfg = active_provider_cfg.get('context_cache', {})
        self.enable_context_cache = bool(cache_cfg.get('enable', False))
        self.cache_expiration_minutes = int(cache_cfg.get('expiration_minutes', 10))
        
        # 4. Contextual Prompt Assembly (Support for Sandbox Injection)
        self.bs_instruction_path = os.path.join(resolve_project_root(), self.llm_bs_config.get('system_instruction', ''))
        raw_instruction = self.instruction_overrides.get('binary_star') or read_prompt_template(self.bs_instruction_path)
        
        # 5. Type-Safe Configuration Slicing (Local Merge with Prompt Injection)
        local_context = {**self.config, **self.global_config}
        self.obs_config = MarketObserverConfig.from_dict(local_context)
        self.session_config = SessionConfig.from_dict(
            local_context, 
            instruction_literal=self.instruction_overrides.get('session')
        )
        self.critic_config = CriticConfig.from_dict(
            local_context, 
            instruction_literal=self.instruction_overrides.get('critic')
        )
        
        # 5.1 Format shared instruction with constants
        self.shared_instruction = safe_format(
            raw_instruction,
            max_rounds=self.max_rounds,
            volatility_baseline_ratio=self.critic_config.regime.volatility_baseline_ratio,
            volatility_extreme_ratio=self.critic_config.regime.volatility_extreme_ratio,
            squeeze_threshold=self.critic_config.regime.squeeze_threshold,
            trend_intensity_threshold=self.critic_config.regime.trend_intensity_threshold,
            trend_intensity_strong=self.critic_config.regime.trend_intensity_strong,
            min_volume_participation_ratio=self.critic_config.regime.min_volume_participation_ratio,
            cvd_intensity_threshold=self.critic_config.regime.cvd_intensity_threshold,
            long_short_imbalance_ratio=self.critic_config.regime.long_short_imbalance_ratio,
            short_heavy_imbalance_ratio=self.critic_config.regime.short_heavy_imbalance_ratio,
            cvd_intensity_extreme=self.critic_config.regime.cvd_intensity_extreme
        )
        
        # 6. Specialized Visualization Pipeline
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines"),
            up_color=self.obs_config.visual.up_color,
            down_color=self.obs_config.visual.down_color,
            bg_color=self.obs_config.visual.bg_color,
            poc_color=self.obs_config.visual.poc_color,
            vah_val_color=self.obs_config.visual.vah_val_color,
            current_price_color=self.obs_config.visual.current_price_color,
            volume_profile_width_ratio=self.obs_config.visual.volume_profile_width_ratio,
            render_dpi=self.obs_config.visual.render_dpi,
            volume_profile_smoothing_sigma=self.obs_config.volume_profile_smoothing_sigma,
            volume_profile_color=self.obs_config.volume_profile_color,
            volume_profile_alpha=self.obs_config.volume_profile_alpha,
            chart_main_panel_weight=self.obs_config.chart_main_panel_weight,
            chart_volume_panel_weight=self.obs_config.chart_volume_panel_weight,
            liquidation_cluster_atr_multiplier=self.obs_config.liquidation_cluster_atr_multiplier,
            liq_max_alpha=self.obs_config.liq_max_alpha,
            liq_min_alpha=self.obs_config.liq_min_alpha,
            liq_legacy_alpha_factor=self.obs_config.liq_legacy_alpha_factor,
            liq_legacy_min_alpha=self.obs_config.liq_legacy_min_alpha,
            liq_legacy_max_alpha=self.obs_config.liq_legacy_max_alpha,
            chart_trendline_peak_count=self.obs_config.chart_trendline_peak_count,
            chart_trendline_window=self.obs_config.chart_trendline_window
        )
        
        # 7. Reasoner Triad Assembly (Dependency Injection)
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol=self.symbol, 
            data_root=self.data_root,
            exchange_client=self.exchange_client,
            chart_generator=self.chart_gen
        )
        
        self.session_agent = SessionAgent(
            config=self.session_config, 
            ai_client=self.client,
            api_timeout=self.api_timeout,
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max
        )
        
        self.critic_agent = CriticAgent(
            config=self.critic_config, 
            ai_client=self.client,
            api_timeout=self.api_timeout, 
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max
        )
        
        self.math_tools = MathTools()

        # v7.7: Congestion Control Implementation (RPM Pacing)
        pacing_seconds = float(gemini_net.get('api_pacing_seconds', 0.0))
        self.congestion_controller = CongestionController(pacing_seconds)
        
        # Inject Congestion Controller into shared components
        self.session_agent.congestion_controller = self.congestion_controller
        self.critic_agent.congestion_controller = self.congestion_controller
        
        self.cache_manager = GeminiCacheManager(
            adapter=self.client,
            congestion_controller=self.congestion_controller
        )
        self.macro_interval = self.obs_config.macro_context.time_interval

        self.math_checker = MathFactChecker(
            math_tools=self.math_tools,
            session_config=self.session_config,
            critic_config=self.critic_config,
            macro_interval=self.macro_interval,
        )

    def execute_flow(self, observation: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """Executes a complete adversarial reasoning cycle (Binary Star Flow).

        Phases: regime benchmarks -> cache setup -> debate -> finalize -> sanitize -> package.
        """
        timestamp = self._resolve_timestamp(observation)
        logger.info(f"BinaryStar: Beginning cycle for {symbol} at {timestamp}...")

        # 1. Inject regime benchmarks (pre-calculated physical constants)
        self._inject_regime_benchmarks(observation)

        # Prune observation and extract visual parts
        pruned_observation = observation.copy()
        if 'visual_context' in pruned_observation:
            del pruned_observation['visual_context']
        observation_json = json.dumps(pruned_observation, indent=2, ensure_ascii=False)
        visual_parts = self._extract_visual_parts(observation)

        try:
            # 2. Set up context cache and agent tools
            cache_resource_name, tools = self._prepare_agent_tools(
                observation_json, symbol, visual_parts)

            # 3. Adversarial Debate Loop
            self.debate_loop = DebateLoop(
                session_agent=self.session_agent,
                critic_agent=self.critic_agent,
                math_checker=self.math_checker,
                max_rounds=self.max_rounds,
                cache_resource_name=cache_resource_name,
                tools=tools,
                visual_parts=visual_parts,
                shared_instruction=self.shared_instruction,
                session_config=self.session_config,
                critic_config=self.critic_config,
            )
            debate_result = self.debate_loop.run(observation, symbol)

            # 4. Finalize and sanitize decision
            final_decision = self._finalize_and_sanitize(
                debate_result, observation, symbol,
                cache_resource_name, tools, visual_parts)

            # 5. Package forensic output
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            return {
                "final_decision": final_decision,
                "debate_history": debate_result["debate_history"],
                "observation": observation,
                "metadata": {
                    "config_snapshot": self.config,
                    "version_control": {
                        "session_hash": get_file_hash(self.session_agent.config.instruction_path),
                        "critic_hash": get_file_hash(self.critic_agent.config.instruction_path),
                        "binary_star_hash": get_file_hash(self.bs_instruction_path),
                        "config_hash": get_file_hash(config_path)
                    }
                }
            }

        except Exception as e:
            logger.error(f"BinaryStar Flow failed fatally: {e}", exc_info=True)
            raise
        finally:
            self._cleanup_cache()

    # ── Private helper methods ──────────────────────────────────────────────

    def _resolve_timestamp(self, observation: Dict[str, Any]) -> str:
        """Standardize forensic timestamp to YYYYMMDD_HHMMSS format."""
        obs_ts = observation.get("observed_at", "")
        if "_" in obs_ts and len(obs_ts) == 15:
            return obs_ts
        try:
            dt = parse_iso_to_utc(obs_ts)
            return dt.strftime(FILE_TIMESTAMP_FORMAT)
        except Exception:
            from datetime import datetime
            return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _inject_regime_benchmarks(self, observation: Dict[str, Any]) -> None:
        """Pre-calculate static market constants to reduce Agent tool calls."""
        try:
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            regime = metrics.get('market_regime', {})

            scalars = MathTools.get_regime_scalars(
                trend_intensity=float(regime.get('trend_intensity', 0)),
                volatility_intensity_index=float(dynamics.get('volatility_intensity_index', 0)),
                normalized_velocity=float(dynamics.get('normalized_velocity', 0)),
                min_velocity_floor=self.session_config.temporal.min_trade_velocity,
                ti_thresh=self.critic_config.regime.trend_intensity_threshold,
                ti_strong=self.critic_config.regime.trend_intensity_strong,
                vr_base=self.critic_config.regime.volatility_baseline_ratio,
                vr_extreme=self.critic_config.regime.volatility_extreme_ratio,
                dilation_dead_water=self.session_config.temporal.temporal_dilation_dead_water,
                dilation_highway=self.session_config.temporal.temporal_dilation_highway,
                dilation_climax=self.session_config.temporal.temporal_dilation_climax,
                dilation_standard=self.session_config.temporal.temporal_dilation_standard,
                weight_dead_water=self.session_config.temporal.temporal_weight_dead_water,
                weight_highway=self.session_config.temporal.temporal_weight_highway,
                weight_climax=self.session_config.temporal.temporal_weight_climax,
                weight_standard=self.session_config.temporal.temporal_weight_standard
            )

            macro_interval_mins = get_interval_minutes(self.macro_interval)
            unit_atr_holding_hours = round((1.0 / scalars["effective_velocity_per_atr"] * macro_interval_mins * scalars["temporal_dilation_factor"]) / 60, 1)
            unit_atr_waiting_hours = round((1.0 / scalars["effective_velocity_per_atr"] * macro_interval_mins) / 60, 1)

            regime['temporal_physics'] = {
                "unit_atr_holding_hours": unit_atr_holding_hours,
                "unit_atr_waiting_hours": unit_atr_waiting_hours
            }
            logger.info(f"BinaryStar: Injected Regime Benchmarks [Holding: {unit_atr_holding_hours}h/ATR, Waiting: {unit_atr_waiting_hours}h/ATR]")
        except Exception as e:
            logger.warning(f"BinaryStar: Failed to inject regime benchmarks: {e}")

    def _prepare_agent_tools(self, observation_json: str, symbol: str,
                             visual_parts: list) -> tuple[str | None, list]:
        """Set up context cache and return the cache resource name and tool list."""
        tool_declarations = [
            {
                "name": "calculate_risk_reward",
                "description": "Calculates the Risk-Reward (RR) ratio for a limit order.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entry": {"type": "NUMBER"},
                        "take_profit": {"type": "NUMBER"},
                        "stop_loss": {"type": "NUMBER"}
                    },
                    "required": ["entry", "take_profit", "stop_loss"]
                }
            },
            {
                "name": "calculate_atr_metrics",
                "description": "Standardizes entry/exit distances using ATR.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entry": {"type": "NUMBER"},
                        "stop_loss": {"type": "NUMBER"},
                        "take_profit": {"type": "NUMBER"},
                        "atr": {"type": "NUMBER"}
                    },
                    "required": ["entry", "stop_loss", "take_profit", "atr"]
                }
            }
        ]

        cache_resource_name = None
        if self.enable_context_cache:
            cache_resource_name = self.cache_manager.create_market_cache(
                symbol=symbol,
                interval=self.macro_interval,
                contents=[observation_json] + visual_parts,
                system_instruction=self.shared_instruction,
                model=self.shared_model,
                ttl_minutes=self.cache_expiration_minutes,
                tools=[types.Tool(function_declarations=tool_declarations)]
            )
        else:
            logger.info(f"BinaryStar: Context Cache is DISABLED. Routing multimodal visual payload statelessly.")

        tools = [
            self.session_agent.calculate_risk_reward,
            self.session_agent.calculate_atr_metrics
        ]
        return cache_resource_name, tools

    def _finalize_and_sanitize(self, debate_result: dict, observation: dict,
                               symbol: str, cache_resource_name: str | None,
                               tools: list, visual_parts: list) -> dict:
        """Run final synthesis (if needed) and sanitize the decision against math truth."""
        last_plan = debate_result["final_decision"]
        debate_history = debate_result["debate_history"]
        early_exit = debate_result["early_exit"]

        # Decision Finalization
        if early_exit:
            logger.info("BinaryStar: Using early-exit plan as final decision.")
            final_decision = last_plan
        else:
            logger.info("BinaryStar: Finalizing consensus decision...")
            final_decision = self.session_agent.execute_session_cycle(
                observation=observation,
                symbol=symbol,
                temperature=self.critic_config.model_temperature,
                agent_name="Session_Synthesis",
                cache_id=cache_resource_name,
                tools=tools,
                debate_history=self.debate_loop._compress_debate_history(debate_history),
                visual_parts=visual_parts,
                system_instruction=self.shared_instruction
            )

        # Physical Parameter Sanitization
        final_math = self.math_checker.verify(final_decision, observation)
        if final_math.get("status") == "VERIFIED":
            tactical = final_decision.get("tactical_parameters", {})
            holding_v = final_math.get("holding_time_verification", {})
            if holding_v:
                tactical["projected_holding_hours"] = holding_v.get("projected_holding_hours", 0)
                tactical["projected_waiting_hours"] = holding_v.get("projected_waiting_hours", 0)
            rr_v = final_math.get("rr_verification", {})
            if rr_v and "rr_ratio" in rr_v:
                tactical["rr_ratio"] = rr_v["rr_ratio"]

        logger.info("BinaryStar: Final decision sanitized against physical truth.")
        return final_decision

    def _cleanup_cache(self) -> None:
        """Proactively purge the session context cache."""
        try:
            if getattr(self, 'enable_context_cache', True) and self.cache_manager.active_cache_id:
                self.cache_manager.delete_market_cache()
        except Exception as e:
            logger.warning(f"BinaryStar: Non-fatal cache cleanup failure: {e}")


    def _extract_visual_parts(self, observation: Dict[str, Any]) -> List[types.Part]:
        """Converts observation visual assets into multimodal Gemini Parts."""
        parts = []
        assets = observation.get('visual_context', {})
        for key, path in assets.items():
            try:
                if path and os.path.exists(path):
                    # v6.15: Explicitly Label visual parts to harden AI spatial reasoning
                    parts.append(types.Part.from_text(text=f"[VISUAL_CONTEXT: {key.upper()}]"))
                    with open(path, 'rb') as f:
                        parts.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
            except Exception as e:
                logger.warning(f"BinaryStar: Visual asset ingestion failed for {path}: {e}")
        return parts
