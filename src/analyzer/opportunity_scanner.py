import os
import logging
from typing import Dict, Any, List, Optional
from src.agent.observer_agent import ObserverAgent
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger

class OpportunityScanner:
    """
    Shared component for market opportunity detection.
    Analyzes 'Truth Bus' (Observation) to determine if a full strategy run is warranted.
    """
    def __init__(self, symbol: str, data_root: str, logger: Optional[logging.Logger] = None, observer: Optional[ObserverAgent] = None):
        self.symbol = symbol
        self.data_root = data_root
        self.logger = logger or setup_logger("OpportunityScanner", propagate = True)
        
        self.config = load_config()

        # Use existing observer or initialize new one
        if observer:
            self.observer = observer
        else:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            self.observer = ObserverAgent(self.config, symbol, api_key, self.data_root)

    def scan(self) -> Dict[str, Any]:
        """
        Executes the observer to gather current market facts.
        """
        self.logger.info(f"Scanner: Commencing structural mapping for {self.symbol}...")
        return self.observer.observe()

    def should_trigger(self, observation: Dict[str, Any]) -> bool:
        """
        Refined Hybrid Trigger Logic:
        1. Momentum Trigger: (Volume Breakout) AND (Volatility Expansion OR Squeeze)
        2. Structural Trigger: (Proximity to Anchor) OR (Liquidation Clusters)
        """
        if "error" in observation:
            self.logger.error(f"Scanner: Observation error - {observation['error']}")
            return False

        metrics = observation['quantitative_metrics']
        regime = metrics['market_regime']
        vol_regime = regime['volatility_regime']
        vol_breakout = float(regime['volume_breakout_ratio'])
        vol_threshold = self.config['observer']['regime_volume_breakout_threshold']
        
        self.logger.info("-" * 40)
        self.logger.info(f"SIGNAL AUDIT | {self.symbol}")
        self.logger.info(f"Volume Breakout: {vol_breakout:.2f} (Threshold: {vol_threshold})")
        self.logger.info(f"Volatility: {vol_regime} (Ratio: {metrics['price_dynamics']['volatility_intensity_index']})")

        # --- A. MOMENTUM TRIGGER (Energy + Action) ---
        # Only trigger momentum if high volume is accompanied by a vol expansion or a tight squeeze
        has_volume = vol_breakout >= vol_threshold
        has_action = vol_regime in ["EXPANSION", "SQUEEZE"]
        
        momentum_met = has_volume and has_action
        if momentum_met:
            self.logger.info(f"Scanner: [READY] MOMENTUM Trigger met (Volume: {vol_breakout:.1f}x + {vol_regime}).")
            return True

        # --- B. STRUCTURAL TRIGGER (Geography) ---
        # Trigger if price is testing a key structural level, even if volume is low (Early Interception)
        topo = metrics['volume_topography']
        anchors = topo['anchors_above'] + topo['anchors_below']
        current_price = metrics['price_dynamics']['current_price']
        atr = metrics['price_dynamics']['atr_macro']
        
        struct_met = False
        struct_threshold = self.config['observer']['regime_structural_proximity_threshold']
        for anchor in anchors:
            dist_atr = abs(current_price - anchor['price']) / (atr + 1e-9)
            if dist_atr < struct_threshold:
                self.logger.info(f"Scanner: [READY] STRUCTURAL Trigger (Proximity to {anchor['type']} @ {anchor['price']:.2f} | Dist: {dist_atr:.2f} ATR).")
                struct_met = True
                break
        
        if struct_met:
            return True

        # --- C. SENTIMENT TRIGGER (Magnets) ---
        sentiment = metrics['sentiment_signals']
        clusters = sentiment['liquidation_clusters']
        if clusters:
            self.logger.info(f"Scanner: [READY] SENTIMENT Trigger ({len(clusters)} liquidation clusters nearby).")
            return True

        # Fallback
        self.logger.info(f"Scanner: [PASS] Momentum ({'MET' if has_volume else 'LOW'} Volume / {'MET' if has_action else 'NORMAL'} Regime) | No key structural test.")
        self.logger.info("-" * 40)
        return False
        
