import os
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from src.infrastructure.ai_client import VisualPart, VisualMode
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.analyzer.math_fact_checker import MathFactChecker
from src.analyzer.confidence_calculator import compute_confidence
from src.agent.debate_loop import DebateLoop
from src.agent.session_agent import SessionAgent, SessionConfig
from src.agent.critic_agent import CriticAgent, CriticConfig
from src.infrastructure.ai_factory import AIFactory
from src.utils.math_utils import MathTools
from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.utils.rate_limiter import CongestionController
from src.utils.pipeline_utils import load_config, get_file_hash, read_prompt_template, safe_format, get_project_version, get_git_commit
from src.utils.datetime_utils import parse_iso_to_utc, FILE_TIMESTAMP_FORMAT, get_interval_minutes
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

# Initialize standard hardened logger for orchestrator telemetry
logger = setup_logger(__name__)


@dataclass(frozen=True)
class BinaryStarConfig:
    """Pre-computed configuration bundle for BinaryStarOrchestrator.

    Consolidates all resolved config values into one injectable object
    so the orchestrator constructor stays focused on wiring, not parsing.
    """

    # ── Network / retry ─────────────────────────────────────────────
    api_timeout: int
    retry_count: int
    retry_multiplier: float
    retry_min: int
    retry_max: int
    max_tool_iterations: int

    # ── Binary Star protocol ────────────────────────────────────────
    max_rounds: int
    shared_model: str
    shared_instruction: str
    bs_instruction_path: str

    # ── Sub-configs ─────────────────────────────────────────────────
    obs_config: MarketObserverConfig
    session_config: SessionConfig
    critic_config: CriticConfig

    @classmethod
    def from_dicts(
        cls,
        config_dict: Dict[str, Any],
        global_config: Dict[str, Any],
        instruction_overrides: Dict[str, str] | None = None,
    ) -> "BinaryStarConfig":
        """Resolve all config values from raw dicts into a frozen bundle."""
        overrides = instruction_overrides or {}

        # LLM / provider
        llm_cfg = global_config["llm"]
        api_timeout = int(llm_cfg["api_timeout_seconds"])
        retry_count = int(llm_cfg["retry_count"])
        max_tool_iterations = int(llm_cfg["max_tool_iterations"])
        retry_strategy = llm_cfg["retry_strategy"]
        retry_multiplier = float(retry_strategy["multiplier"])
        retry_min = int(retry_strategy["min_seconds"])
        retry_max = int(retry_strategy["max_seconds"])
        bs_cfg = global_config["binary_star"]
        active_provider = llm_cfg.get("active_provider")
        if not active_provider:
            raise ValueError("active_provider is not set in llm configuration.")
        active_provider = active_provider.lower()
        provider_cfg = llm_cfg.get(active_provider, {})
        shared_model = provider_cfg.get("model")
        if not shared_model:
            raise ValueError(f"Missing 'model' in llm.{active_provider} configuration.")

        # Shared instruction
        bs_instruction_path = os.path.join(
            resolve_project_root(),
            bs_cfg.get("system_instruction", ""),
        )
        raw_instruction = (
            overrides.get("binary_star")
            or read_prompt_template(bs_instruction_path)
        )

        # Sub-configs
        local_context = {**config_dict, **global_config}
        obs_config = MarketObserverConfig.from_dict(local_context)
        session_config = SessionConfig.from_dict(
            local_context, instruction_literal=overrides.get("session"),
        )
        critic_config = CriticConfig.from_dict(
            local_context, instruction_literal=overrides.get("critic"),
        )

        # Format shared instruction with constants
        shared_instruction = safe_format(
            raw_instruction,
            max_rounds=bs_cfg["max_rounds"],
            debate_history_json="[Provided in user prompt — cumulative round-by-round record]",
        )

        return cls(
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max,
            max_tool_iterations=max_tool_iterations,
            max_rounds=int(bs_cfg["max_rounds"]),
            shared_model=str(shared_model),
            shared_instruction=shared_instruction,
            bs_instruction_path=bs_instruction_path,
            obs_config=obs_config,
            session_config=session_config,
            critic_config=critic_config,
        )


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
                 exchange_client: Optional[AbstractExchangeClient] = None,
                 bs_config: Optional[BinaryStarConfig] = None,
                 global_config: Optional[Dict[str, Any]] = None):
        """Initializes the orchestrator as a central resource and configuration hub.

        Args:
            config_dict: Strategy configuration (strategy_config.yaml).
            api_key: API key for the active LLM provider.
            data_root: Logical root directory for forensic asset persistence.
            symbol: Trading pair (e.g., BTCUSDT).
            instruction_overrides: In-memory overrides for agent prompt templates.
            exchange_client: Optional pre-configured exchange client for testing.
            bs_config: Pre-built BinaryStarConfig (bypasses internal config parsing).
            global_config: Optional pre-resolved global config (with per-symbol
                           overrides applied). If not provided, loads raw from disk.
        """
        self.config = config_dict
        self.api_key = api_key
        self.data_root = data_root
        self.symbol = symbol
        self.instruction_overrides = instruction_overrides or {}

        # ── 0. Global config & logging ──────────────────────────────
        if global_config is not None:
            self.global_config = global_config
        else:
            self.global_config = load_config('config/global_config.yaml')
        session_log_path = os.path.join(resolve_project_root(), self.data_root, "session.log")
        setup_logger("src.agent", log_level=logging.INFO, log_file=session_log_path,
                     max_bytes=10 * 1024 * 1024, backup_count=5,
                     propagate=False)
        logger.debug(f"Binary Star Session activated | root={self.data_root}")

        # ── 1. Resolve configuration bundle ─────────────────────────
        if bs_config is None:
            bs_config = BinaryStarConfig.from_dicts(
                config_dict, self.global_config, self.instruction_overrides,
            )
        self.bs = bs_config

        # Expose frequently-accessed values directly (backward compatibility)
        self.obs_config = bs_config.obs_config
        self.session_config = bs_config.session_config
        self.critic_config = bs_config.critic_config
        self.api_timeout = bs_config.api_timeout
        self.retry_count = bs_config.retry_count
        self.retry_multiplier = bs_config.retry_multiplier
        self.retry_min = bs_config.retry_min
        self.retry_max = bs_config.retry_max
        self.max_tool_iterations = bs_config.max_tool_iterations
        self.max_rounds = bs_config.max_rounds
        self.shared_model = bs_config.shared_model
        self.shared_instruction = bs_config.shared_instruction
        self.bs_instruction_path = bs_config.bs_instruction_path

        # ── 2. Infrastructure clients ───────────────────────────────
        self.client = AIFactory.create_client(api_key=api_key, config_dict=self.global_config)
        self._visual_mode = self.client.visual_mode
        self.exchange_client: AbstractExchangeClient = exchange_client or BinanceFuturesClient()

        # ── 3. Visualization pipeline ───────────────────────────────
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
            chart_trendline_window=self.obs_config.chart_trendline_window,
        )

        # ── 4. Reasoning triad ──────────────────────────────────────
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol=self.symbol,
            data_root=self.data_root,
            exchange_client=self.exchange_client,
            chart_generator=self.chart_gen,
        )
        self.math_tools = MathTools()

        self.session_agent = SessionAgent(
            config=self.session_config, ai_client=self.client,
            api_timeout=self.api_timeout, retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min, retry_max=self.retry_max,
        )
        self.critic_agent = CriticAgent(
            config=self.critic_config, ai_client=self.client,
            api_timeout=self.api_timeout, retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min, retry_max=self.retry_max,
        )

        # ── 5. Congestion control & caching ─────────────────────────
        llm_cfg = self.global_config['llm']
        pacing_seconds = float(llm_cfg.get('api_pacing_seconds', 0.0))
        self.congestion_controller = CongestionController(pacing_seconds)
        self.session_agent.congestion_controller = self.congestion_controller
        self.critic_agent.congestion_controller = self.congestion_controller

        self.macro_interval = self.obs_config.macro_context.time_interval
        self.math_checker = MathFactChecker(
            math_tools=self.math_tools,
            session_config=self.session_config,
            critic_config=self.critic_config,
            macro_interval=self.macro_interval,
        )

    def execute_flow(self, observation: Dict[str, Any], symbol: str,
                     progress_callback=None) -> Dict[str, Any]:
        """Executes a complete adversarial reasoning cycle (Binary Star Flow).

        Phases: regime benchmarks -> cache setup -> debate -> finalize -> sanitize -> package.

        Args:
            progress_callback: Optional fn(stage, activity, stage_label=..., status=...)
                for progress reporting. Called at key phase transitions.
        """
        timestamp = self._resolve_timestamp(observation)
        logger.info(f"[{symbol}] cycle begin | ts={timestamp}")

        # 1. Inject regime benchmarks (pre-calculated physical constants)
        self._inject_regime_benchmarks(observation)

        if progress_callback:
            progress_callback(stage=2, activity="Preparing LLM context…")

        visual_parts, visual_text = self._load_visual_assets(observation)

        tool_declarations = MathTools.get_tool_declarations()

        logger.info(
            "[%s] visual assets loaded | mode=%s | images=%d | text=%s",
            symbol, self._visual_mode.value,
            len(visual_parts),
            f"{len(visual_text)} chars" if visual_text else "none",
        )

        # Session begin — adapter manages cache internally
        logger.info(
            "[%s] session begin | model=%s | visual_parts=%d | tools=%d",
            symbol, self.shared_model, len(visual_parts), len(tool_declarations),
        )
        self.client.begin_session(
            system_instruction=self.shared_instruction,
            tools=tool_declarations,
            visual_parts=visual_parts,
            model=self.shared_model,
        )

        try:
            # Debate Loop

            self.debate_loop = DebateLoop(
                session_agent=self.session_agent,
                critic_agent=self.critic_agent,
                math_checker=self.math_checker,
                max_rounds=self.max_rounds,
                tools=tool_declarations,
                visual_text=visual_text,
                shared_instruction=self.shared_instruction,
                session_config=self.session_config,
                critic_config=self.critic_config,
            )
            debate_result = self.debate_loop.run(observation, symbol,
                                                   progress_callback=progress_callback)

            # Finalize
            if progress_callback:
                progress_callback(stage=4, activity="Synthesizing final decision…")

            final_decision = self._finalize_and_sanitize(
                debate_result, observation, symbol,
                tools=tool_declarations,
                visual_text=visual_text,
                progress_callback=progress_callback,
            )

            # Package
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            return {
                "final_decision": final_decision,
                "debate_history": debate_result["debate_history"],
                "observation": observation,
                "metadata": {
                    "config_snapshot": self.config,
                    "version_control": {
                        "project_version": get_project_version(),
                        "git_commit": get_git_commit(),
                        "session_hash": get_file_hash(self.session_agent.config.instruction_path),
                        "critic_hash": get_file_hash(self.critic_agent.config.instruction_path),
                        "binary_star_hash": get_file_hash(self.bs_instruction_path),
                        "config_hash": get_file_hash(config_path)
                    }
                }
            }

        except Exception as e:
            logger.error(f"Binary Star flow failed | error={e}", exc_info=True)
            raise
        finally:
            logger.info("[%s] session released", symbol)
            self.client.end_session()

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
            from datetime import datetime, timezone
            return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def _inject_regime_benchmarks(self, observation: Dict[str, Any]) -> None:
        """Pre-calculate static market constants to reduce Agent tool calls."""
        try:
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            regime = metrics.get('market_regime', {})

            from src.utils.math_utils import build_physics_config
            physics = build_physics_config(self.session_config, self.critic_config)
            scalars = MathTools.get_regime_scalars(
                trend_intensity=float(regime.get('trend_intensity', 0)),
                volatility_intensity_index=float(dynamics.get('volatility_intensity_index', 0)),
                normalized_velocity=float(dynamics.get('normalized_velocity', 0)),
                physics=physics,
            )

            macro_interval_mins = get_interval_minutes(self.macro_interval)
            unit_atr_holding_hours = round((1.0 / scalars["effective_velocity_per_atr"] * macro_interval_mins * scalars["temporal_dilation_factor"]) / 60, 1)
            unit_atr_waiting_hours = round((1.0 / scalars["effective_velocity_per_atr"] * macro_interval_mins) / 60, 1)

            regime['temporal_physics'] = {
                "unit_atr_holding_hours": unit_atr_holding_hours,
                "unit_atr_waiting_hours": unit_atr_waiting_hours
            }
            logger.info(f"[{self.symbol}] regime benchmarks | hold={unit_atr_holding_hours}h/ATR | wait={unit_atr_waiting_hours}h/ATR")
        except Exception as e:
            logger.warning(f"failed to inject regime benchmarks | error={e}")

    def _finalize_and_sanitize(self, debate_result: dict, observation: dict,
                               symbol: str,
                               tools: list,
                               visual_text: str | None,
                               progress_callback=None) -> dict:
        """Run final synthesis (if needed) and sanitize the decision against math truth."""
        last_plan = debate_result["final_decision"]
        debate_history = debate_result["debate_history"]
        early_exit = debate_result["early_exit"]

        # Decision Finalization
        if early_exit:
            logger.info(f"[{symbol}] using early-exit plan as final decision")
            final_decision = last_plan
        else:
            # Check if Critic's final verdict is TERMINAL — abort to NEUTRAL
            last_history = debate_history[-1] if debate_history else {}
            last_critic = last_history.get("critic", {}) if isinstance(last_history, dict) else {}
            last_veto = (last_critic.get("veto_level") or "").upper()
            if last_veto == "TERMINAL":
                # Build veto trajectory from all rounds
                veto_trail = []
                for entry in debate_history:
                    r = entry.get("round", "?")
                    v = entry.get("critic", {}).get("veto_level", "?")
                    veto_trail.append(f"R{r} {v}")
                trail_str = " → ".join(veto_trail)

                # Extract the last Critic's invalidation tags
                invalids = last_critic.get("invalidations") or []
                inval_tags = ", ".join(
                    inv.split(" - ")[0] if " - " in str(inv) else str(inv)
                    for inv in invalids
                )

                logger.warning(
                    f"[{symbol}] TERMINAL persisted at max_rounds → forcing NEUTRAL | "
                    f"veto_trail={trail_str} | invalids={inval_tags}"
                )
                final_decision = {
                    "opinion": "NEUTRAL",
                    "confidence_score": 0,
                    "tactical_parameters": {},
                    "reasoning_chain": (
                        f"**FORCED NEUTRAL** — Critic TERMINAL persisted at max_rounds.\n\n"
                        f"**Veto trail**: {trail_str}\n"
                        f"**Root causes**: {inval_tags or 'N/A'}\n\n"
                        f"Debate aborted. No structurally valid trade could be synthesized."
                    ),
                    "critic_impact": "Debate aborted — Critic TERMINAL persisted at max_rounds; forced NEUTRAL before Session_Synthesis could respond.",
                }
            else:
                logger.info(f"[{symbol}] finalizing consensus decision")
                final_decision = self.session_agent.execute_session_cycle(
                    observation=observation,
                    symbol=symbol,
                    temperature=self.critic_config.model_temperature,
                    agent_name="Session_Synthesis",
                    tools=tools,
                    debate_history=self.debate_loop._compress_debate_history(debate_history),
                    visual_text=visual_text,
                    system_instruction=self.shared_instruction,
                )

        # Physical Parameter Sanitization (skip NEUTRAL — no trade params to verify)
        if final_decision.get("opinion") == "NEUTRAL":
            final_decision["confidence_score"] = 0
            return final_decision

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

        # Replace LLM-generated confidence_score with Python-computed value
        final_decision["confidence_score"] = compute_confidence(
            final_decision, observation, final_math,
            debate_history,
            self.critic_config.regime,
            self.critic_config.risk,
        )

        logger.info(f"[{symbol}] final decision sanitized")

        return final_decision



    def _load_visual_assets(self, observation: Dict[str, Any]) -> tuple[List[VisualPart], str | None]:
        """Load visual assets based on provider visual mode."""
        vc = observation.get('visual_context', {})

        match self._visual_mode:
            case VisualMode.IMAGE:
                parts: list[VisualPart] = []
                for key in ('macro_snapshot', 'micro_snapshot'):
                    path = vc.get(key)
                    if path and os.path.exists(path):
                        try:
                            with open(path, 'rb') as f:
                                parts.append(VisualPart(
                                    mime_type='image/png',
                                    data=f.read(),
                                    label=f'[VISUAL_CONTEXT: {key.upper()}]',
                                ))
                        except Exception as e:
                            logger.warning(f"failed to read visual asset {path}: {e}")
                return parts, None

            case VisualMode.TEXT:
                text_blocks: list[str] = []
                for label, key in [
                    ('VISUAL_CONTEXT: MACRO_SNAPSHOT', 'macro_snapshot_summary'),
                    ('VISUAL_CONTEXT: MICRO_SNAPSHOT', 'micro_snapshot_summary'),
                ]:
                    path = vc.get(key)
                    if path and os.path.exists(path):
                        try:
                            with open(path, 'r') as f:
                                text_blocks.append(f'{label}\n\n{f.read()}')
                        except Exception as e:
                            logger.warning(f"failed to read visual asset {path}: {e}")
                text = '\n\n'.join(text_blocks) if text_blocks else None
                return [], text

            case VisualMode.NONE:
                return [], None
