import logging
import json
import os
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

from src.infrastructure.gemini.cache_manager import GeminiCacheManager
from src.agent.observer_agent import ObserverAgent, ObserverConfig
from src.agent.strategist_agent import StrategistAgent, StrategistConfig
from src.agent.critic_agent import CriticAgent, CriticConfig
from src.agent.tools.math_tools import MathTools
from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.chart_generator import ChartGenerator
from src.utils.agent_utils import load_config, get_file_hash, read_prompt_template
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)

class BinaryStarOrchestrator:
    """
    Manages the 'Binary Star' adversarial reasoning flow.
    Replaces the sequential Triad Flow with a single-session/shared-cache debate.
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
        self.max_rounds = int(self.bs_config['agent_model_max_debate_rounds'])
        self.stop_threshold = int(self.bs_config['agent_model_debate_stop_threshold'])
        self.cache_expiration = int(self.bs_config['agent_model_cache_expiration_minutes'])
        self.shared_model = self.bs_config['agent_model']
        
        # 4. Prompt & Instruction Assembly
        instruction_path = self.bs_config.get('agent_model_system_instruction')
        self.shared_instruction = read_prompt_template(instruction_path)
        
        # 5. Type-Safe Configuration Slicing
        # Orchestrator handles the 'config mapping' responsibility for production-grade decoupling
        shared_meta = self.global_config['agent_model_shared_config']
        max_tool_iterations = int(shared_meta['max_tool_iterations'])
        strategy_intent = str(self.global_config['strategy_intent'])
        
        self.obs_config = ObserverConfig.from_dict(self.config)
        self.strat_config = StrategistConfig.from_dict(
            strategist_cfg=self.config['strategist'],
            observer_cfg=self.config['observer'],
            strategy_intent=strategy_intent,
            max_tool_iterations=max_tool_iterations
        )
        self.critic_config = CriticConfig.from_dict(self.config)
        
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
            chart_generator=self.chart_gen,
            ai_client=self.client
        )
        
        self.strategist = StrategistAgent(
            config=self.strat_config, 
            api_timeout=self.api_timeout,
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max,
            ai_client=self.client
        )
        
        self.critic = CriticAgent(
            config=self.critic_config, 
            api_timeout=self.api_timeout, 
            retry_count=self.retry_count,
            retry_multiplier=self.retry_multiplier,
            retry_min=self.retry_min,
            retry_max=self.retry_max,
            ai_client=self.client
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
        3. Critic Audit (Context-aware)
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
                self.strategist.calculate_risk_reward, 
                self.strategist.calculate_atr_metrics, 
                self.strategist.calculate_structural_proximity, 
                self.strategist.project_holding_time
            ]
            
            # Phase 0: Initialize Forensic Truth Bus (Shared Context Cache)
            logger.info(f"BinaryStar: [INIT] Requesting Truth Bus cache for {symbol} ({self.macro_interval})...")
            cache_resource_name = self.cache_manager.create_market_cache(
                symbol=symbol,
                interval=self.macro_interval,
                contents=contents,
                system_instruction=self.shared_instruction,
                ttl_minutes=self.cache_expiration,
                model=self.shared_model
            )

            # Phase 1 & 2: The Adversarial Debate Loop
            # The Strategist proposes, the Critic audits, and we loop if logical risk is high.
            current_round = 0
            last_critique = None
            last_draft = None
            
            while current_round <= self.max_rounds:
                # Drafting / Re-Drafting
                logger.info(f"BinaryStar: [PHASE 1] Strategist generating thesis (Round {current_round})...")
                last_draft = self.strategist.draft(
                    None, symbol, cache_id=cache_resource_name, tools=tools, 
                    previous_critique=last_critique
                )
                
                # Adversarial Auditing
                logger.info(f"BinaryStar: [PHASE 2] Critic performing adversarial audit (Round {current_round})...")
                last_critique = self.critic.audit(None, last_draft, symbol, cache_id=cache_resource_name, tools=tools)
                
                # Check for Early Stopping (The "Enough" Condition)
                skepticism_score = int(last_critique.get('skepticism_score', 100))
                if skepticism_score < self.stop_threshold:
                    logger.info(f"BinaryStar: Skepticism Score ({skepticism_score}) < Threshold ({self.stop_threshold}). Loop terminated early.")
                    break
                    
                current_round += 1
                
            # Phase 3: The Synthesis (Final Hardening)
            # The Strategist synthesizes the final consensus decision based on the LAST博弈 round.
            logger.info("BinaryStar: [PHASE 3] Strategist synthesizing final hardened decision...")
            final_decision = self.strategist.synthesize(last_draft, last_critique, cache_id=cache_resource_name, tools=tools)
            
            # Phase 4: Metadata Fingerprinting & Session Closure
            # Records the 'Immutable DNA' of the logic that generated this decision.
            from src.utils.agent_utils import get_file_hash
            from src.utils.path_utils import resolve_project_root
            project_root = resolve_project_root()
            config_path = os.path.join(project_root, 'config', 'agent_config.yaml')
            
            metadata = {
                "version_control": {
                    "observer_hash": get_file_hash(self.strategist.config.role_prompt_path.replace('strategist.md', 'observer.md')),
                    "strategist_hash": get_file_hash(self.strategist.config.role_prompt_path),
                    "critic_hash": get_file_hash(self.critic.config.role_prompt_path),
                    "config_hash": get_file_hash(config_path),
                    "logic_timestamp": timestamp
                },
                "cache_info": {
                    "resource_name": cache_resource_name,
                    "ttl": self.cache_expiration
                }
            }
            
            logger.info(f"BinaryStar: [COMPLETE] Decision synthesized for {symbol}. Session Result packaged.")
            
            return {
                "observation": observation,
                "cache_id": cache_resource_name,
                "draft": last_draft,
                "critique": last_critique,
                "final_decision": final_decision,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"BinaryStar Flow failed: {e}", exc_info=True)
            raise
        finally:
            # Note: Cache naturally expires via TTL
            pass

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
