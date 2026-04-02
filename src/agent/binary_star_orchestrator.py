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
from src.utils.pipeline_utils import load_config, get_file_hash, read_prompt_template, resolve_data_root
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class BinaryStarOrchestrator:
    """
    Manages the 'Binary Star' adversarial reasoning flow.
    Replaces the sequential Triad Flow with a single-session/shared-cache debate (Session Agent vs Audit).
    """
    
    def __init__(self, config_dict: Dict[str, Any], api_key: str, data_root: str):
        """
        Initializes the 'Binary Star' orchestrator as a central resource hub.
        Standardizes physical connections and type-safe configuration distribution.
        """
        self.config = config_dict
        self.api_key = api_key
        self.data_root = resolve_data_root(data_root)
        
        # 1. Central Resource Hub: Shared Clients
        # We initialize these ONCE and share across the reasoning triad
        self.client = genai.Client(api_key=api_key)
        self.binance_client = BinanceFuturesClient()
        
        # 2. Global Environmental Configuration
        self.global_config = load_config('config/global_config.yaml')
        gemini_net = self.global_config['network']['gemini']
        self.api_timeout = int(gemini_net['api_timeout_seconds'])
        self.retry_count = int(gemini_net['retry_count'])
        
        retry_strategy = gemini_net['retry_strategy']
        self.retry_multiplier = float(retry_strategy['multiplier'])
        self.retry_min = int(retry_strategy['min_seconds'])
        self.retry_max = int(retry_strategy['max_seconds'])
        
        # 3. Binary Star Session Management
        self.bs_config = self.config['binary_star']
        self.max_rounds = int(self.bs_config['max_rounds'])
        self.skepticism_halt_limit = int(self.bs_config['skepticism_halt_limit'])
        self.cache_expiration = int(self.bs_config['cache_expiration_minutes'])
        self.shared_model = self.bs_config['model']
        
        # 4. Prompt & Instruction Assembly
        instruction_path = self.bs_config.get('system_instruction')
        self.shared_instruction = read_prompt_template(instruction_path)
        
        # 5. Type-Safe Configuration Slicing
        # Orchestrator handles the 'config mapping' responsibility for production-grade decoupling
        max_tool_iterations = int(gemini_net.get('max_tool_iterations', 5))
        strategy_intent = str(self.config.get('strategy_intent', ""))
        
        self.obs_config = MarketObserverConfig.from_dict(self.config)
        self.session_config = SessionConfig.from_dict(self.config)
        self.critic_config = CriticConfig.from_dict(self.config)
        
        # 6. Specialized Visualization Assets Manager
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines")
        )
        
        # 7. Reasoner Triad Assembly (The Brain)
        # Full Dependency Injection ensures physical auth isolation and testability.
        self.observer = MarketObserver(
            config=self.obs_config,
            symbol=self.global_config['system']['default_symbol'], 
            data_root=self.data_root,
            binance_client=self.binance_client,
            chart_generator=self.chart_gen
        )
        
        self.session_agent = SessionAgent(
            config=self.session_config, 
            api_timeout=self.api_timeout,
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max,
            ai_client=self.client,
            model=self.shared_model
        )
        
        self.critic_agent = CriticAgent(
            config=self.critic_config, 
            api_timeout=self.api_timeout, 
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max,
            ai_client=self.client,
            model=self.shared_model
        )
        
        # Logic Components
        self.cache_manager = GeminiCacheManager(self.client)
        self.math_tools = MathTools()
        
        # Record Macro Interval for identification
        self.macro_interval = self.obs_config.macro_context.time_interval

    def execute_flow(self, observation: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """
        Executes a complete Binary Star cycle:
        1. Context Caching (Truth Bus)
        2. Strategist Draft (Phase A)
        3. Audit Audit (Context-aware)
        4. Strategist Synthesis (Phase B)
        """
        # v5.10 Hardening: Session ID and Timestamp are anchored to the MARKET observation time
        # Standardized format: YYYYMMDD_HHMMSS
        obs_ts = observation.get("timestamp", "")
        
        # If the timestamp already follows the compact standard (e.g. 20260402_113057), use it directly
        if "_" in obs_ts and len(obs_ts) == 15:
            timestamp = obs_ts
        else:
            # Fallback for ISO format or legacy data
            try:
                from src.utils.datetime_utils import parse_iso_to_utc, FILE_TIMESTAMP_FORMAT
                dt = parse_iso_to_utc(obs_ts)
                timestamp = dt.strftime(FILE_TIMESTAMP_FORMAT)
            except:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        cache_name = f"market_topography_{symbol}_{timestamp}"
        
        logger.info(f"BinaryStar: Creating context cache for {symbol} using model {self.shared_model}...")
        
        # Observation is a dict, we convert it to JSON for caching
        observation_json = json.dumps(observation, indent=2, ensure_ascii=False)
        contents = [observation_json]
        
        # We also need images for true multimodal caching
        visual_parts = self._extract_visual_parts(observation)
        contents.extend(visual_parts)
        
        try:
            # 1. Prepare Tools (Mandatory in Binary Star)
            tools = [
                self.session_agent.calculate_risk_reward, 
                self.session_agent.calculate_atr_metrics, 
                self.session_agent.calculate_structural_proximity, 
                self.session_agent.project_holding_time
            ]
            
            # Phase 0: Initialize Audit Context Bus (Shared Context Cache)
            logger.info(f"BinaryStar: [INIT] Requesting Truth Bus cache for {symbol} ({self.macro_interval})...")
            
            # v5.10 Context Caching: Manual Tool Schema Injection.
            # We bake the TOOLS and SYSTEM_INSTRUCTIONS into the cache resource.
            # We define tools as explicit dictionaries to satisfy Pydantic requirements.
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
                    "description": "Standardizes entry/exit distances using ATR (Average True Range).",
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
                    "description": "Calculates distance from SL to structural levels (POC, VAH, VAL) in ATR units.",
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
                    "description": "Predicts the time required to reach the Take Profit target.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "entry": {"type": "NUMBER"},
                            "take_profit": {"type": "NUMBER"},
                            "atr": {"type": "NUMBER"},
                            "trend_intensity": {"type": "NUMBER"},
                            "macro_interval_minutes": {"type": "NUMBER"}
                        },
                        "required": ["entry", "take_profit", "atr", "trend_intensity", "macro_interval_minutes"]
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
            
            # Phase 1 & 2: The Adversarial Debate Loop (With Trajectory Memory)
            # current_round starts at 1 for human-centric indexing (Round 1, Round 2...)
            current_round = 1
            critic_results = None
            last_draft = None
            debate_history = []
            
            # Static Truth Tracker
            # NOTE: math_fact_check is recalculated each round because it verifies the 
            # UNIQUE tactical parameters (Entry/SL/TP) proposed in each specific reasoning draft.
            math_fact_check = None

            while current_round <= self.max_rounds:
                # 1. Phase 1: Drafting / Re-Drafting
                logger.info(f"BinaryStar: [PHASE 1] Session Agent generating thesis (Round {current_round})...")
                last_draft = self.session_agent.draft(
                    observation, symbol, cache_id=cache_resource_name, tools=tools, 
                    critic_feedback=critic_results
                )
                
                # 2. Phase 2: Adversarial Critic Evaluation (Truth Injection: Python verifies LLM math)
                logger.info(f"BinaryStar: [PHASE 2] Critic Agent performing adversarial evaluation (Round {current_round})...")
                
                # 2a. Physical Verification (The "Fact Check" turn)
                math_fact_check = self._assemble_math_fact_check(last_draft, observation)
                
                # 2b. Semantic Evaluation (Pass facts to Critic)
                critic_results = self.critic_agent.evaluate(
                    observation=observation, 
                    draft_plan=last_draft, 
                    symbol=symbol,
                    cache_id=cache_resource_name,
                    math_fact_check=math_fact_check,
                    tools=tools # Restore tools for Two-Phase Loop
                )
                
                # 3. Decision Logic & Convergence Check
                try:
                    raw_score = critic_results.get('skepticism_score', 100)
                    skepticism_score = int(float(str(raw_score))) # Handle "40", 40, "40.0"
                except (ValueError, TypeError):
                    logger.warning(f"BinaryStar: Invalid skepticism_score format ({raw_score}). Falling back to 100.")
                    skepticism_score = 100

                logger.info(f"BinaryStar [Critique]: Round {current_round} Score: {skepticism_score} | Verdict: {(critic_results or {}).get('audit_impact', 'N/A')}")
                
                # Track Critic Trail
                debate_history.append({
                    "round": current_round,
                    "draft": last_draft,
                    "critic": critic_results,
                    "math_fact_check": math_fact_check
                })

                if skepticism_score < self.skepticism_halt_limit:
                    logger.info(f"BinaryStar: Skepticism Score ({skepticism_score}) < Threshold ({self.skepticism_halt_limit}). Loop terminated early.")
                    break
                    
                current_round += 1
                
            # The Session Agent synthesizes the final consensus decision based on the LAST debate round + the Math Truth.
            logger.info("BinaryStar: [PHASE 3] Session Agent synthesizing final hardened decision...")
            final_decision = self.session_agent.synthesize(
                draft_plan=last_draft, 
                critic_results=critic_results, 
                cache_id=cache_resource_name, 
                math_fact_check=math_fact_check,
                observation=observation, # CRITICAL: Pass observation for Zero-Knowledge runs
                tools=tools # Restore tools for Two-Phase Loop
            )
            
            # Phase 4: Metadata Fingerprinting & Session Closure
            # Records the 'Immutable DNA' of the logic that generated this decision.
            from src.utils.pipeline_utils import get_file_hash
            from src.utils.path_utils import resolve_project_root
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            
            
            logger.info(f"BinaryStar: [COMPLETE] Decision synthesized for {symbol}. Session Result packaged.")
            
            # v5.10 Hardening: Package the session result with forensic parity.
            # Session ID and redundant keys have been pruned for zero-entropy output.
            return {
                "final_decision": final_decision,
                "debate_history": debate_history,
                "observation": observation,
                "metadata": {
                    "config_snapshot": self.config,
                    "version_control": {
                        "session_hash": get_file_hash(self.session_agent.config.role_prompt_path),
                        "critic_hash": get_file_hash(self.critic_agent.config.role_prompt_path),
                        "config_hash": get_file_hash(config_path)
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"BinaryStar Flow failed: {e}", exc_info=True)
            raise
        finally:
            # Dual-Insurance: Proactively purge the Truth Bus cache.
            # Fallback: The TTL from config handles system-level crashes.
            try:
                self.cache_manager.delete_market_cache()
            except Exception as e:
                logger.warning(f"BinaryStar: Non-fatal failure during cache cleanup: {e}")

    def _assemble_math_fact_check(self, draft: Dict[str, Any], observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assembles a deterministic 'Math Truth' package for the current draft.
        Eliminates the need for LLM Tool Calling during Critic and Synthesis phases.
        """
        try:
            # v5.10 Optimization: Handle AI execution errors or neutral stances
            if draft.get("error"):
                return {
                    "status": "ERROR",
                    "reason": f"Physical verification impossible: Draft failed with {draft.get('agent')} error."
                }

            # Corrected: SessionAgent uses "opinion", not "verdict"
            opinion = draft.get("opinion", "NEUTRAL")
            if opinion == "NEUTRAL":
                return {
                    "status": "SKIPPED",
                    "reason": "Physical verification only required for active trade proposals."
                }

            tactical = draft.get('tactical_parameters') or {}
            entry = float(tactical.get('entry', 0) or 0)
            sl = float(tactical.get('stop_loss', 0) or 0)
            tp = float(tactical.get('take_profit', 0) or 0)
            
            # Extract observation geometry (Truth Bus)
            metrics = observation.get('quantitative_metrics', {})
            dynamics = metrics.get('price_dynamics', {})
            topo = metrics.get('volume_profile', {})
            
            atr = float(dynamics.get('atr_macro', 1.0))
            poc = float(topo.get('poc', 0))
            vah = float(topo.get('vah', 0))
            val = float(topo.get('val', 0))
            
            # Extract regime context
            regime = observation.get('regime_analysis', {})
            trend_intensity = float(regime.get('trend_intensity', 0))
            
            # 1. Verify RR
            rr_results = self.math_tools.calculate_risk_reward(entry, tp, sl)
            
            # 2. Verify ATR Buffers
            atr_metrics = self.math_tools.calculate_atr_metrics(entry, sl, tp, atr)
            
            # 3. Verify Structural Proximity
            proximity = self.math_tools.calculate_structural_proximity(sl, atr, poc, vah, val)
            
            # 4. Project Holding Time
            holding_time = self.math_tools.project_holding_time(
                entry, tp, atr, trend_intensity, 
                int(self.config['analysis_window']['macro_context']['time_interval'].replace('h', '')) * 60, # Approximation for minutes
                self.session_config.min_trade_velocity
            )
            
            return {
                "rr_verification": rr_results,
                "atr_volatility_verification": atr_metrics,
                "structural_armor_verification": proximity,
                "holding_time_verification": holding_time
            }
        except Exception as e:
            logger.error(f"BinaryStar: Math fact check assembly failed: {e}")
            return {"error": f"Physical verification failed: {e}"}

    def _extract_visual_parts(self, observation: Dict[str, Any]) -> List[types.Part]:
        """Extracts image data from visual assets into Gemini Parts."""
        parts = []
        assets = observation.get('visual_assets', {})
        for label, path in assets.items():
            try:
                import os
                if path and os.path.exists(path):
                    with open(path, 'rb') as f:
                        parts.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))
            except Exception as e:
                logger.warning(f"Failed to load visual asset {path}: {e}")
        return parts
