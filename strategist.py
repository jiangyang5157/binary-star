#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.observer_agent import ObserverAgent
from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from src.utils.agent_utils import load_config, load_global_config
from src.utils.logger_utils import setup_logger
from src.utils.json_utils import save_json
from src.utils.datetime_utils import parse_iso_to_utc, sanitize_timestamp
from src.utils.path_utils import find_project_root

# Initialize pipeline logger
logger = setup_logger("StrategistOrchestrator")

def calculate_math_fact_check(observation: Dict[str, Any], draft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extracted logic for the [Middleware Computation Gate].
    Calculates deterministic math facts to prevent LLM hallucinations.
    """
    # If action is NEUTRAL, we bypass math check (trigger [CLEAR] in Critic)
    if draft.get('action') == 'NEUTRAL':
        return None

    limit_order = draft.get('limit_order')
    if not (limit_order and all(k in limit_order and limit_order[k] is not None for k in ('entry', 'take_profit', 'stop_loss'))):
        return None

    try:
        entry = float(limit_order['entry'])
        tp = float(limit_order['take_profit'])
        sl = float(limit_order['stop_loss'])
        
        # Extract ATR from the correct nested location in the observation
        metrics = observation.get('quantitative_metrics', {})
        dynamics = metrics.get('price_dynamics', {})
        atr = float(dynamics.get('atr_macro', 1.0))
        
        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)
        
        # Extract Regime and Trend Intensity
        regime = metrics.get('market_regime', {})
        trend_intensity = float(regime.get('trend_intensity', 1.0))
        
        # Load Agent Config for Floor (Enforce mandatory config)
        agent_cfg = load_config()
        velocity_floor = float(agent_cfg['strategist']['min_temporal_efficiency'])
        
        # [Unit Fragility Fix] Determine hours per macro candle
        from src.utils.datetime_utils import get_interval_seconds
        macro_interval = agent_cfg['observer']['macro_analysis_context']['time_interval']
        macro_hours = get_interval_seconds(macro_interval) / 3600
        
        effective_velocity = atr * max(trend_intensity, velocity_floor)
        
        # Extract Topology for SL buffer verification
        topography = metrics.get('volume_topography', {})
        poc = topography.get('poc')
        vah = topography.get('vah')
        val = topography.get('val')

        def dist_to_atr(anchor):
            """Calculates a signed vector from Anchor to SL in ATR units."""
            try:
                if anchor is not None and atr > 0:
                    # (Price_SL - Price_Anchor) / ATR
                    # BULLISH: SL < Anchor -> Negative
                    # BEARISH: SL > Anchor -> Positive
                    return round((sl - float(anchor)) / atr, 2)
            except (ValueError, TypeError):
                pass
            return None

        return {
            "actual_rr": round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0,
            "entry_to_sl_atr": round(sl_dist / atr, 2) if atr > 0 else 0,
            "entry_to_tp_atr": round(tp_dist / atr, 2) if atr > 0 else 0,
            "sl_to_poc_atr": dist_to_atr(poc),
            "sl_to_vah_atr": dist_to_atr(vah),
            "sl_to_val_atr": dist_to_atr(val),
            "projected_holding_hours": round((tp_dist / effective_velocity) * macro_hours, 2) if effective_velocity > 0 else 0
        }
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Math Fact Check calculation failed: {e}")
        return None

def run_full_triad_flow(observation: Dict[str, Any], strategist_agent: StrategistAgent, critic_agent: CriticAgent) -> Dict[str, Any]:
    """
    Standardizes the 3-pass reasoning interaction (Triad logic).
    Maintained as a public function for backward compatibility with offline audit scripts.
    """
    logger.info("Triad Step 1/3: Drafting initial strategic plan...")
    draft = strategist_agent.draft(observation)
    
    logger.info("Triad Step 2/3: Performing adversarial audit...")
    
    # [Middleware Computation Gate] Intercept Draft and Inject Math Facts
    math_fact_check = calculate_math_fact_check(observation, draft)
    if math_fact_check:
        logger.info(f"Math Fact Check generated: {math_fact_check}")

    critique = critic_agent.audit(observation, draft, math_fact_check=math_fact_check)
    
    logger.info("Triad Step 3/3: Synthesizing final decision...")
    final_decision = strategist_agent.synthesize(observation, draft, critique)
    
    return {
        "observation": observation,
        "draft": draft,
        "critique": critique,
        "final_decision": final_decision
    }

def archive_strategy_result(symbol: str, timestamp: datetime, result: Any, data_root: str, target_dir: str) -> str:
    """
    Standardized archival for all pipeline results.
    Maintained as a public function for consistency.
    """
    project_root = find_project_root()
    output_dir = os.path.join(project_root, data_root, target_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    ts_str = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
    ts_suffix = sanitize_timestamp(ts_str)
    filename = f"{symbol}_{target_dir}_{ts_suffix}.json"
    output_file = os.path.join(output_dir, filename)
    
    save_json(result, output_file)
    return output_file

class StrategistOrchestrator:
    """
    The Master Trading Orchestrator.
    
    This class manages the high-fidelity 'Reasoning Triad' lifecycle:
    1. Observe: Invokes the ObserverAgent for multimodal topographical mapping.
    2. Draft: Phase A of the StrategistAgent (Initial strategic plan).
    3. Audit: Invokes the CriticAgent with 'Math Fact Check' telemetry injection.
    4. Synthesis: Phase B of the StrategistAgent (Risk-hardened final decision).
    5. Notify: Dispatches smart alerts via StrategyNotifier.
    6. Archive: Stores the full forensic session for later post-mortem review.
    """
    def __init__(self, symbol: str, data_root: str):
        """
        Initializes the orchestrator with the full agent triad.
        """
        self.symbol = symbol
        self.data_root = data_root
        self.config = load_config()
        
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
            
        # Initialize the Specialized Forensic Trio
        self.observer = ObserverAgent(self.config, symbol, api_key=self.api_key, data_root=data_root)
        self.strategist = StrategistAgent(self.config, api_key=self.api_key)
        self.critic = CriticAgent(self.config, api_key=self.api_key)

    def execute_pipeline(self, timestamp_str: Optional[str] = None):
        """Runs the complete fresh prediction cycle."""
        logger.info(f"=== Starting Trading Pipeline for {self.symbol} ===")
        
        # 1. Prepare temporal context
        timestamp = parse_iso_to_utc(timestamp_str) if timestamp_str else None

        try:
            # 2. Stage 1: Observe (Market Topography)
            logger.info("Stage 1: Gathering market facts...")
            observation = self.observer.observe(timestamp=timestamp, data_root=self.data_root)
            
            # 3. Stages 2-4: Reasoning Triad (Draft -> Audit -> Synthesis)
            session_result = run_full_triad_flow(observation, self.strategist, self.critic)
            
            # 4. Stage 5: Notification (Actionable Alerts)
            self._handle_notifications(session_result)

            # 5. Stage 6: Archival (Forensic History)
            output_file = archive_strategy_result(
                symbol=self.symbol, 
                timestamp=observation.get('timestamp'), 
                result=session_result, 
                data_root=self.data_root, 
                target_dir="strategies"
            )
            logger.info(f"Pipeline complete. Strategy archived at: {output_file}")

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        finally:
            logger.info("=== Pipeline Operation Concluded ===")

    def _handle_notifications(self, session_result: Dict[str, Any]):
        """Delegates notification filtering to the Smart Notifier."""
        try:
            from src.infrastructure.notifications.email_notifier import StrategyNotifier
            notifier = StrategyNotifier(data_root=self.data_root)
            notifier.notify_strategy(self.symbol, session_result, save_local=False)
        except Exception as e:
            logger.error(f"Notification service failure: {e}")

def main():
    """CLI entry point for the Trading Orchestrator."""
    parser = argparse.ArgumentParser(description="Strategist Master - Fresh Prediction Pipeline")
    parser.add_argument("--symbol", type=str, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--timestamp", type=str, help="Optional historical timestamp (ISO)")
    parser.add_argument("--data_root", type=str, required=True, help="Data directory root")
    args = parser.parse_args()
    
    # Load global defaults for missing CLI args
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    if not symbol:
        logger.error("Error: Symbol not provided and no default found in global_config.yaml")
        sys.exit(1)
        
    try:
        orchestrator = StrategistOrchestrator(symbol=symbol, data_root=args.data_root)
        orchestrator.execute_pipeline(timestamp_str=args.timestamp)
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
