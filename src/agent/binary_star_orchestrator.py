import logging
import json
import os
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from src.infrastructure.gemini.cache_manager import GeminiCacheManager
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.agent.session_agent import SessionAgent, SessionConfig
from src.agent.critic_agent import CriticAgent, CriticConfig
from src.utils.math_utils import MathTools
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.utils.pipeline_utils import load_config, get_file_hash, read_prompt_template, resolve_data_root, safe_format
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
    2. Physical Verification: AI drafts are cross-referenced against Python-native
       math fact-checks to prevent hallucination in trade geometry.
    3. Adversarial Hardening: Iterative debate rounds ensure the final trade
       blueprint is logically sound and structurally shielded.
    """
    
    def __init__(self, config_dict: Dict[str, Any], api_key: str, data_root: str):
        """Initializes the orchestrator as a central resource and configuration hub.
        
        Args:
            config_dict: The global strategy configuration (strategy_config.yaml).
            api_key: Authenticated Google GenAI API key.
            data_root: Logical root directory for forensic asset persistence.
        """
        self.config = config_dict
        self.api_key = api_key
        self.data_root = resolve_data_root(data_root)
        
        # 0. Global Configuration Merging (Physical Split maintained for Snapshot Purity)
        self.global_config = load_config('config/global_config.yaml')
        # self.config.update(self.global_config)  # [DECOUPLED] Removed to keep strategy snapshot pure
        
        # 0. Forensic Logging Initialization (Standardized v5.10 Telemetry)
        session_log_path = os.path.join(resolve_project_root(), self.data_root, 'session.log')
        setup_logger("src", log_file=session_log_path)
        logger.info(f"--- Forensic Session Initialized: {self.data_root} ---")
        
        # 1. Shared Infrastructure Clients
        self.client = genai.Client(api_key=api_key)
        self.binance_client = BinanceFuturesClient()
        
        # 2. Global Environment Constants (Resolved from Global Config)
        gemini_net = self.global_config['network']['gemini']
        self.api_timeout = int(gemini_net['api_timeout_seconds'])
        self.retry_count = int(gemini_net['retry_count'])
        self.max_tool_iterations = int(gemini_net['max_tool_iterations'])
        
        retry_strategy = gemini_net['retry_strategy']
        self.retry_multiplier = float(retry_strategy['multiplier'])
        self.retry_min = int(retry_strategy['min_seconds'])
        self.retry_max = int(retry_strategy['max_seconds'])
        
        # 3. Binary Star Protocol Parameters
        self.bs_config = self.config['binary_star']
        self.max_rounds = int(self.bs_config['max_rounds'])
        self.skepticism_halt_limit = int(self.bs_config['skepticism_halt_limit'])
        self.cache_expiration = int(self.bs_config['cache_expiration_minutes'])
        self.shared_model = self.bs_config['model']
        
        # 4. Contextual Prompt Assembly
        self.bs_instruction_path = os.path.join(resolve_project_root(), self.bs_config.get('system_instruction', ''))
        raw_instruction = read_prompt_template(self.bs_instruction_path)
        self.shared_instruction = safe_format(raw_instruction, max_rounds=self.max_rounds)
        
        # 5. Type-Safe Configuration Slicing (Local Merge for Initialization)
        local_context = {**self.config, **self.global_config}
        self.obs_config = MarketObserverConfig.from_dict(local_context)
        self.session_config = SessionConfig.from_dict(local_context)
        self.critic_config = CriticConfig.from_dict(local_context)
        
        # 6. Specialized Visualization Pipeline
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines")
        )
        
        # 7. Reasoner Triad Assembly (Dependency Injection)
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol=self.global_config['system']['default_symbol'], 
            data_root=self.data_root,
            binance_client=self.binance_client,
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
        2. Drafting: The Session Agent proposes a thesis after reading the topography.
        3. Audit: The Critic Agent performs an adversarial audit of the draft.
        4. Hardening: Loops through debate rounds until convergence or max_rounds.
        5. Synthesis: Final decision delivery.
        
        Args:
            observation: Market topographical telemetry (Metrics + Visuals).
            symbol: Trading pair identifier (e.g., BTCUSDT).
            
        Returns:
            A forensic session dictionary containing decision, history, and metadata.
            
        Raises:
            Exception: If cache creation or reasoning cycle fails fatally.
        """
        obs_ts = observation.get("timestamp", "")
        
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
                            "entry": {"type": "NUMBER"},
                            "take_profit": {"type": "NUMBER"},
                            "atr": {"type": "NUMBER"},
                            "trend_intensity": {"type": "NUMBER"},
                            "interval_minutes": {"type": "NUMBER"},
                            "min_velocity_floor": {"type": "NUMBER"},
                            "holding_time_modifier": {"type": "NUMBER"}
                        },
                        "required": ["entry", "take_profit", "atr", "trend_intensity", "interval_minutes"]
                    }
                }
            ]
            
            cache_resource_name = self.cache_manager.create_market_cache(
                symbol=symbol,
                interval=self.macro_interval,
                contents=[observation_json] + visual_parts,
                system_instruction=self.shared_instruction,
                model=self.shared_model,
                ttl_minutes=int(self.bs_config.get("cache_expiration_minutes", 10)),
                tools=[types.Tool(function_declarations=tool_declarations)]
            )
            
            # Shared tools available across both agents
            tools = [
                self.session_agent.calculate_risk_reward, 
                self.session_agent.calculate_atr_metrics, 
                self.session_agent.calculate_structural_proximity, 
                self.session_agent.project_holding_time
            ]
            
            # 2. Adversarial Debate Loop
            current_round = 1
            critic_results = None
            last_draft = None
            debate_history = []
            math_fact_check = None

            while current_round <= self.max_rounds:
                # Drafting / Re-Drafting
                logger.info(f"BinaryStar: Round {current_round} - Generating Session Thesis...")
                last_draft = self.session_agent.draft(
                    observation, symbol, cache_id=cache_resource_name, tools=tools, 
                    critic_feedback=critic_results
                )
                
                # Adversarial Audit (Math Fact Check Injection)
                logger.info(f"BinaryStar: Round {current_round} - Performing Adversarial Audit...")
                math_fact_check = self._assemble_math_fact_check(last_draft, observation)
                
                critic_results = self.critic_agent.evaluate(
                    observation=observation, 
                    draft_plan=last_draft, 
                    symbol=symbol,
                    cache_id=cache_resource_name,
                    math_fact_check=math_fact_check,
                    tools=tools
                )
                
                # Score Telemetry & Termination Check
                skepticism_score = int(float(str(critic_results.get('skepticism_score', 100))))
                logger.info(f"BinaryStar [Critique]: Round {current_round} Score: {skepticism_score}")
                
                debate_history.append({
                    "round": current_round,
                    "draft": last_draft,
                    "critic": critic_results,
                    "math_fact_check": math_fact_check
                })

                if skepticism_score < self.skepticism_halt_limit:
                    logger.info(f"BinaryStar: Skepticism resolved ({skepticism_score} < {self.skepticism_halt_limit}). Convergence achieved.")
                    break
                    
                current_round += 1
                
            # 3. Decision Synthesis (Final consensus hardened by Math Truth)
            logger.info("BinaryStar: Finalizing consensus decision...")
            final_decision = self.session_agent.synthesize(
                draft_plan=last_draft, 
                critic_results=critic_results, 
                cache_id=cache_resource_name, 
                math_fact_check=math_fact_check,
                observation=observation, 
                tools=tools
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
                        "session_hash": get_file_hash(self.session_agent.config.role_prompt_path),
                        "critic_hash": get_file_hash(self.critic_agent.config.role_prompt_path),
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
                self.cache_manager.delete_market_cache()
            except Exception as e:
                logger.warning(f"BinaryStar: Non-fatal cache cleanup failure: {e}")

    def _assemble_math_fact_check(self, draft: Dict[str, Any], observation: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates deterministic mathematical truth for an AI draft.
        
        This logic offloads complex trade geometry (RR, ATR, Isolation) to Python code, 
        ensuring the audit loop is anchored by physical market reality.
        
        Args:
            draft: The current tactical proposal from the Session Analyst.
            observation: Baseline topographical telemetry.
            
        Returns:
            A compliance dictionary containing verified metrics and a truth verdict.
        """
        try:
            # Handle draft error or neutral stance
            if draft.get("error"):
                return {"status": "ERROR", "reason": "Draft execution failed."}

            opinion = draft.get("opinion", "NEUTRAL")
            if opinion == "NEUTRAL":
                return {"status": "SKIPPED", "reason": "Neutral proposal requires no math audit."}

            tactical = draft.get('tactical_parameters', {})
            entry = float(tactical.get('entry', 0) or 0)
            sl = float(tactical.get('stop_loss', 0) or 0)
            tp = float(tactical.get('take_profit', 0) or 0)
            
            # Topography Metrics
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            topo = metrics.get('volume_profile', {})
            
            atr = float(dynamics.get('atr_macro', 1.0))
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
                entry, tp, atr, trend_intensity, 
                get_interval_minutes(self.macro_interval),
                self.session_config.min_trade_velocity,
                self.session_config.holding_time_modifier
            )
            
            # Compliance Verdict Synthesis
            is_trending = trend_intensity >= self.critic_config.trend_intensity_threshold
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
        assets = observation.get('visual_assets', {})
        for path in assets.values():
            try:
                if path and os.path.exists(path):
                    with open(path, 'rb') as f:
                        parts.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
            except Exception as e:
                logger.warning(f"BinaryStar: Visual asset ingestion failed for {path}: {e}")
        return parts
