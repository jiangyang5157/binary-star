import logging
import json
import os
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

from src.infrastructure.gemini.cache_manager import GeminiCacheManager
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.agent.session_agent import SessionAgent, SessionConfig
from src.agent.critic_agent import CriticAgent, CriticConfig
from src.utils.math_utils import MathTools
from src.infrastructure.exchange.base_client import AbstractExchangeClient
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
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
    def __init__(self, 
                 config_dict: Dict[str, Any], 
                 api_key: str, 
                 data_root: str,
                 instruction_overrides: Optional[Dict[str, str]] = None):
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
        self.instruction_overrides = instruction_overrides or {}
        
        # 0. Global Configuration Merging (Physical Split maintained for Snapshot Purity)
        self.global_config = load_config('config/global_config.yaml')
        
        # 0. Forensic Logging Initialization (Standardized v5.10 Telemetry)
        # Always enable file logging for forensic audit trails (Reverted v6.50)
        session_log_path = os.path.join(resolve_project_root(), self.data_root, 'session.log')
        setup_logger("", log_file=session_log_path)
        logger.info(f"--- Forensic Session Initialized: {self.data_root} ---")
        
        # 1. Shared Infrastructure Clients
        self.client = genai.Client(api_key=api_key)
        self.exchange_client: AbstractExchangeClient = BinanceFuturesClient()
        
        # 2. Global Environment Constants (Resolved from Global Config)
        gemini_net = self.global_config['network']['gemini']
        self.api_timeout = int(gemini_net['api_timeout_seconds'])
        self.retry_count = int(gemini_net['retry_count'])
        self.max_tool_iterations = int(gemini_net['max_tool_iterations'])
        
        retry_strategy = gemini_net['retry_strategy']
        self.retry_multiplier = float(retry_strategy['multiplier'])
        self.retry_min = int(retry_strategy['min_seconds'])
        self.retry_max = int(retry_strategy['max_seconds'])
        self.cache_expiration_minutes = int(gemini_net['cache_expiration_minutes'])
        self.enable_context_cache = bool(gemini_net['enable_context_cache'])
        
        # 3. Binary Star Protocol Parameters
        self.bs_config = self.config['binary_star']
        self.max_rounds = int(self.bs_config['max_rounds'])
        self.shared_model = self.bs_config['model']
        
        # 4. Contextual Prompt Assembly (Support for Sandbox Injection)
        self.bs_instruction_path = os.path.join(resolve_project_root(), self.bs_config.get('system_instruction', ''))
        raw_instruction = self.instruction_overrides.get('binary_star') or read_prompt_template(self.bs_instruction_path)
        self.shared_instruction = safe_format(raw_instruction, max_rounds=self.max_rounds)
        
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
        
        # 6. Specialized Visualization Pipeline
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines"),
            up_color=self.obs_config.up_color,
            down_color=self.obs_config.down_color,
            bg_color=self.obs_config.bg_color,
            poc_color=self.obs_config.poc_color,
            vah_val_color=self.obs_config.vah_val_color,
            current_price_color=self.obs_config.current_price_color,
            volume_profile_width_ratio=self.obs_config.volume_profile_width_ratio,
            render_dpi=self.obs_config.render_dpi,
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
            symbol=self.global_config['system']['default_symbol'], 
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
        
        self.cache_manager = GeminiCacheManager(self.client)
        self.math_tools = MathTools()
        self.macro_interval = self.obs_config.macro_context.time_interval

    def execute_flow(self, observation: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """Executes a complete adversarial reasoning cycle (Binary Star Flow).
        
        This cycle involves:
        1. Context Caching: Initializing the multimodal Truth Bus.
           (初始化真理总线：在 Gemini Cache 中锁定物理快照，防止 Agent 产生幻觉)
        2. Planning: The Session Agent proposes a thesis plan after reading topography.
           (规划阶段：Session Agent 提出初步交易假设)
        3. Audit: The Critic Agent performs an adversarial audit of the plan.
           (审计阶段：Critic Agent 针对数学和结构风险进行否定性盘问)
        4. Hardening: Loops through debate rounds until convergence or max_rounds.
           (硬化循环：通过多轮辩论不断修正计划，直到质疑分低于阈值)
        5. Finalization: Synthesis of the final decision under high mathematical discipline.
           (最终合成：在冷温度下执行最后一次合成，将共识固化为 JSON 指令)
        
        Args:
            observation: Market topographical telemetry (Metrics + Visuals).
            symbol: Trading pair identifier (e.g., BTCUSDT).
            
        Returns:
            A forensic session dictionary containing decision, history, and metadata.
            
        Raises:
            Exception: If cache creation or reasoning cycle fails fatally.
        """
        obs_ts = observation.get("observed_at", "")
        
        # Standardize forensic timestamp (YYYYMMDD_HHMMSS)
        if "_" in obs_ts and len(obs_ts) == 15:
            timestamp = obs_ts
        else:
            try:
                dt = parse_iso_to_utc(obs_ts)
                timestamp = dt.strftime(FILE_TIMESTAMP_FORMAT)
            except Exception:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        logger.info(f"BinaryStar: Beginning cycle for {symbol} at {timestamp}...")
        
        # 1. Truth Bus Initialization (Context Caching)
        observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        visual_parts = self._extract_visual_parts(observation)
        
        try:
            # v5.10 Context Caching: Manual Tool Schema Injection.
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
                },
                {
                    "name": "calculate_structural_proximity",
                    "description": "Measures SL-to-structure isolation in ATR units.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "stop_loss": {"type": "NUMBER"},
                            "atr": {"type": "NUMBER"},
                            "poc": {"type": "NUMBER"},
                            "vah": {"type": "NUMBER"},
                            "val": {"type": "NUMBER"}
                        },
                        "required": ["stop_loss", "atr"]
                    }
                },
                {
                    "name": "project_holding_time",
                    "description": "Predicts trade duration based on market velocity floor.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "current_price": {"type": "NUMBER"},
                            "entry": {"type": "NUMBER"},
                            "take_profit": {"type": "NUMBER"},
                            "atr": {"type": "NUMBER"},
                            "trend_intensity": {"type": "NUMBER"},
                            "volatility_expansion_index": {"type": "NUMBER"},
                            "interval_minutes": {"type": "NUMBER"},
                            "min_velocity_floor": {"type": "NUMBER"}
                        },
                        "required": ["current_price", "entry", "take_profit", "atr", "trend_intensity", "volatility_expansion_index", "interval_minutes"]
                    }
                },
                {
                    "name": "calculate_opportunity_cost",
                    "description": "Quantifies the 'Cost of Cowardice' (volatility missed during neutral stance).",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "missed_range": {"type": "NUMBER", "description": "The price move delta that was missed."},
                            "atr_macro": {"type": "NUMBER", "description": "Current market volatility for normalization."}
                        },
                        "required": ["missed_range", "atr_macro"]
                    }
                },
                {
                    "name": "calculate_mae_stress",
                    "description": "Evaluates trade stress / MAE against move volatility.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "mae_distance": {"type": "NUMBER", "description": "The maximum adverse excursion recorded."},
                            "max_atr_used": {"type": "NUMBER", "description": "Volatility benchmark used for stress calculation."}
                        },
                        "required": ["mae_distance", "max_atr_used"]
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
            

            # Shared tools available across both agents
            tools = [
                self.session_agent.calculate_risk_reward, 
                self.session_agent.calculate_atr_metrics, 
                self.session_agent.calculate_structural_proximity,
                self.session_agent.calculate_opportunity_cost,
                self.session_agent.calculate_mae_stress,
                self.session_agent.project_holding_time
            ]
            
            # 2. Adversarial Debate Loop
            current_round = 1
            critic_results = None
            last_plan = None
            debate_history = []
            math_fact_check = None
            early_exit = False

            while current_round <= self.max_rounds:
                # Planning / Refinement
                logger.info(f"BinaryStar: Round {current_round} - Generating Session Thesis (Planning State)...")
                last_plan = self.session_agent.execute_session_cycle(
                    observation=observation, 
                    symbol=symbol,
                    temperature=self.session_config.model_temperature,
                    agent_name=f"Session_Planning_R{current_round}",
                    cache_id=cache_resource_name, 
                    tools=tools, 
                    debate_history=debate_history,
                    visual_parts=visual_parts,
                    system_instruction=self.shared_instruction
                )

                
                # Adversarial Audit (Math Fact Check Injection)
                logger.info(f"BinaryStar: Round {current_round} - Performing Adversarial Audit...")
                math_fact_check = self._assemble_math_fact_check(last_plan, observation)
                
                critic_results = self.critic_agent.evaluate(
                    observation=observation, 
                    last_plan=last_plan, 
                    symbol=symbol,
                    debate_history=debate_history,
                    cache_id=cache_resource_name,
                    math_fact_check=math_fact_check,
                    tools=tools,
                    visual_parts=visual_parts,
                    system_instruction=self.shared_instruction
                )

                
                # Score Telemetry
                skepticism_score = int(float(str(critic_results.get('skepticism_score', 100))))
                veto_level = critic_results.get('veto_level', 'UNKNOWN').upper()
                logger.info(f"BinaryStar Audit [R{current_round}]: Score={skepticism_score} | Veto={veto_level}")
                
                debate_history.append({
                    "round": current_round,
                    "plan": last_plan,
                    "critic": critic_results,
                    "math_fact_check": math_fact_check
                })
                
                # Early Exit Check: If Critic issues a PASS, the plan is hardened.
                if veto_level == "PASS":
                    logger.info(f"BinaryStar: Pristine plan detected in Round {current_round}. Triggering early exit.")
                    early_exit = True
                    break
                    
                current_round += 1
                
            # 3. Decision Finalization (Convergent Synthesis)
            if early_exit:
                logger.info("BinaryStar: Using early-exit plan as final decision.")
                final_decision = last_plan
            else:
                # STRATEGIC ALPHA: We hijack the Auditor's cold temperature (0.3) for 
                # the final synthesis. This forces the Session Agent to shift from 
                # 'Creative Planning' (0.7) to 'Disciplined Execution' (0.3), ensuring 
                # that the final technical parameters are deterministic and rigorous.
                logger.info("BinaryStar: Finalizing consensus decision...")
                final_decision = self.session_agent.execute_session_cycle(
                    observation=observation, 
                    symbol=symbol,
                    temperature=self.critic_config.model_temperature,
                    agent_name="Session_Synthesis",
                    cache_id=cache_resource_name, 
                    tools=tools, 
                    debate_history=debate_history,
                    visual_parts=visual_parts,
                    system_instruction=self.shared_instruction
                )

            
            # 4. Forensic Packaging
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            
            return {
                "final_decision": final_decision,
                "debate_history": debate_history,
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
            # Proactively purge session context cache
            try:
                if getattr(self, 'enable_context_cache', True) and self.cache_manager.active_cache_id:
                    self.cache_manager.delete_market_cache()
            except Exception as e:
                logger.warning(f"BinaryStar: Non-fatal cache cleanup failure: {e}")


    def _assemble_math_fact_check(self, plan: Dict[str, Any], observation: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates deterministic mathematical truth for an AI proposal.
        
        This logic offloads complex trade geometry (RR, ATR, Isolation) to Python code, 
        ensuring the audit loop is anchored by physical market reality.
        
        Args:
            plan: The current tactical proposal from the Session Analyst.
            observation: Baseline topographical telemetry.
            
        Returns:
            A compliance dictionary containing verified metrics and a truth verdict.
        """
        try:
            # Handle plan error or neutral stance
            if plan.get("error"):
                return {"status": "ERROR", "reason": "Proposal execution failed."}

            opinion = plan.get("opinion", "NEUTRAL")
            if opinion == "NEUTRAL":
                return {"status": "SKIPPED", "reason": "Neutral proposal requires no math audit."}

            tactical = plan.get('tactical_parameters', {})
            entry = float(tactical.get('entry', 0) or 0)
            sl = float(tactical.get('stop_loss', 0) or 0)
            tp = float(tactical.get('take_profit', 0) or 0)
            
            # Topography Metrics
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            topo = metrics.get('volume_profile', {})
            
            atr = float(dynamics['atr_macro'])
            poc = float(topo.get('poc', 0))
            vah = float(topo.get('vah', 0))
            val = float(topo.get('val', 0))
            
            regime = observation.get('regime_analysis', {})
            trend_intensity = float(regime.get('trend_intensity', 0))
            
            # Verified Metrics Calculation
            rr_results = self.math_tools.calculate_risk_reward(entry, tp, sl)
            atr_metrics = self.math_tools.calculate_atr_metrics(entry, sl, tp, atr)
            proximity = self.math_tools.calculate_structural_proximity(sl, atr, poc, vah, val)
            
            holding_time = self.math_tools.project_holding_time(
                current_price=float(tactical.get('current_price', 0) or 0),
                entry=entry, take_profit=tp, atr=atr, 
                trend_intensity=trend_intensity, 
                volatility_expansion_index=float(dynamics['volatility_expansion_index']),

                interval_minutes=get_interval_minutes(self.macro_interval),
                min_velocity_floor=self.session_config.min_trade_velocity,
                vr_base=self.critic_config.volatility_baseline_ratio,
                vr_extreme=self.critic_config.volatility_extreme_ratio,
                ti_strong=self.critic_config.trend_intensity_strong,
                ti_thresh=self.critic_config.trend_intensity_threshold,
                dilation_dead_water=self.session_config.temporal_dilation_dead_water,
                dilation_highway=self.session_config.temporal_dilation_highway,
                dilation_climax=self.session_config.temporal_dilation_climax,
                dilation_standard=self.session_config.temporal_dilation_standard
            )
            
            # Compliance Verdict Synthesis
            is_trending = abs(trend_intensity) >= self.critic_config.trend_intensity_threshold
            min_rr = self.critic_config.min_rr_trending if is_trending else self.critic_config.min_rr_ranging
            
            # Shielding check
            buffer = self.critic_config.structural_buffer_atr
            prox_values = [v for v in proximity.values() if v is not None]
            is_shielded = (any(v < -buffer for v in prox_values) if opinion == "BULLISH" 
                           else any(v > buffer for v in prox_values))
            
            compliance = {
                "rr_is_valid": rr_results.get("rr_ratio", 0) >= min_rr,
                "sl_is_shielded": is_shielded,
                "atr_volatility_is_logical": atr_metrics.get("entry_to_sl_atr", 0) < self.critic_config.poc_gravity_atr_distance
            }
            
            return {
                "status": "VERIFIED",
                "rr_verification": rr_results,
                "atr_volatility_verification": atr_metrics,
                "structural_armor_verification": proximity,
                "holding_time_verification": holding_time,
                "compliance_verdict": compliance
            }
        except Exception as e:
            logger.error(f"BinaryStar: Math fact check failed: {e}")
            return {"error": "VERIFICATION_FAILURE", "details": str(e)}

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
