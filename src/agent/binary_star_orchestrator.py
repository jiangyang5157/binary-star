import logging
import json
import os
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from src.infrastructure.gemini.cache_manager import GeminiCacheManager
from src.analyzer.topography_engine import ObserverAgent, ObserverConfig
from src.agent.session_agent import SessionAgent, SessionConfig
from src.agent.audit_agent import AuditAgent, AuditConfig
from src.utils.math_utils import MathTools
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.utils.pipeline_utils import load_config, get_file_hash, read_prompt_template
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
        self.data_root = data_root
        
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
        
        self.obs_config = ObserverConfig.from_dict(self.config)
        self.session_config = SessionConfig.from_dict(self.config)
        self.audit_config = AuditConfig.from_dict(self.config)
        
        # 6. Specialized Visualization Assets Manager
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(resolve_project_root(), self.data_root, "klines")
        )
        
        # 7. Reasoner Triad Assembly (The Brain)
        # Full Dependency Injection ensures physical auth isolation and testability.
        self.observer = ObserverAgent(
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
        
        self.audit = AuditAgent(
            config=self.audit_config, 
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
        timestamp = observation.get('timestamp', 'unknown')
        cache_name = f"market_topography_{symbol}_{timestamp.replace(':', '-')}"
        
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
            # TEMPORARY DISABLE CACHE TO RESTORE RELIABILITY 
            # We revisit the 400 INVALID_ARGUMENT (Cache vs Tools) in a separate engineering task.
            cache_resource_name = None 
            
            # Phase 1 & 2: The Adversarial Debate Loop (With Trajectory Memory)
            current_round = 0
            audit_results = None
            last_draft = None
            debate_history = []
            convergence_path = []
            while current_round <= self.max_rounds:
                # Drafting / Re-Drafting
                logger.info(f"BinaryStar: [PHASE 1] Session Agent generating thesis (Round {current_round})...")
                last_draft = self.session_agent.draft(
                    observation, symbol, cache_id=cache_resource_name, tools=tools, 
                    previous_audit=audit_results
                )
                
                # Adversarial Auditing
                logger.info(f"BinaryStar: [PHASE 2] Audit Agent performing adversarial audit (Round {current_round})...")
                audit_results = self.audit.audit(observation, last_draft, symbol, cache_id=cache_resource_name, tools=tools)
                
                # Check for Early Stopping (The "Enough" Condition)
                try:
                    raw_score = audit_results.get('skepticism_score', 100)
                    skepticism_score = int(float(str(raw_score))) # Handle "40", 40, "40.0"
                except (ValueError, TypeError):
                    logger.warning(f"BinaryStar: Invalid skepticism_score format ({raw_score}). Falling back to 100.")
                    skepticism_score = 100

                # Track Audit Trail
                debate_history.append({
                    "round": current_round,
                    "draft": last_draft,
                    "audit": audit_results
                })
                convergence_path.append(skepticism_score)

                if skepticism_score < self.stop_threshold:
                    logger.info(f"BinaryStar: Skepticism Score ({skepticism_score}) < Threshold ({self.stop_threshold}). Loop terminated early.")
                    break
                    
                current_round += 1
                
            # Phase 3: The Synthesis (Final Hardening)
            # The Session Agent synthesizes the final consensus decision based on the LAST debate round.
            logger.info("BinaryStar: [PHASE 3] Session Agent synthesizing final hardened decision...")
            final_decision = self.session_agent.synthesize(last_draft, audit_results, cache_id=cache_resource_name, tools=tools)
            
            # Phase 4: Metadata Fingerprinting & Session Closure
            # Records the 'Immutable DNA' of the logic that generated this decision.
            from src.utils.pipeline_utils import get_file_hash
            from src.utils.path_utils import resolve_project_root
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
            
            metadata = {
                "version_control": {
                    "session_agent_hash": get_file_hash(self.session_agent.config.role_prompt_path),
                    "audit_hash": get_file_hash(self.audit.config.role_prompt_path),
                    "config_hash": get_file_hash(config_path),
                    "logic_timestamp": timestamp
                }
            }
            
            logger.info(f"BinaryStar: [COMPLETE] Decision synthesized for {symbol}. Session Result packaged.")
            
            # Package the session result with full audit metadata
            return {
                "symbol": symbol,
                "timestamp": timestamp,
                "final_decision": final_decision,
                "audit": audit_results,
                "debate_history": debate_history,
                "observation": observation,
                "regime_snapshot": self.config.get('regime_parameters', {}),
                "metadata": {
                    "session_id": f"{symbol}_{timestamp}",
                    "total_rounds": current_round + 1,
                    "convergence_path": convergence_path,
                    "version_control": {
                        "session_agent_hash": get_file_hash(self.session_agent.config.role_prompt_path),
                        "audit_hash": get_file_hash(self.audit.config.role_prompt_path),
                        "config_hash": get_file_hash(config_path),
                        "logic_timestamp": timestamp
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
