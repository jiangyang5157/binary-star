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
        self.logger = logger or setup_logger("OpportunityScanner")
        
        # Use existing observer or initialize new one
        if observer:
            self.observer = observer
        else:
            self.config = load_config()
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                # We still warn, but it's now technically required by ObserverAgent's original API
                self.logger.warning("Scanner: GEMINI_API_KEY not found. Note that ObserverAgent typically requires it.")
            self.observer = ObserverAgent(self.config, symbol, api_key, self.data_root)

    def scan(self) -> Dict[str, Any]:
        """
        Executes the observer to gather current market facts.
        """
        self.logger.info(f"Scanner: Commencing mapping for {self.symbol}...")
        return self.observer.observe()

    def should_trigger(self, observation: Dict[str, Any]) -> bool:
        """
        Multi-factor check to determine if the market is 'interesting'.
        Renamed from is_worth_it for clarity.
        """
        if "error" in observation:
            self.logger.error(f"Scanner: Observation error - {observation['error']}")
            return False

        metrics = observation['quantitative_metrics']
        regime = metrics['market_regime']
        intensity = float(regime['trend_intensity'])
        vol_regime = regime['volatility_regime']
        vol_breakout = float(regime['volume_breakout_ratio'])
        
        # Detailed Signal Log (Debugging Friendly)
        self.logger.info("-" * 40)
        self.logger.info(f"SIGNAL AUDIT | {self.symbol}")
        self.logger.info(f"Trend Intensity: {intensity:.2f} ({regime['price_trend_regime']})")
        self.logger.info(f"Volatility: {vol_regime} (Ratio: {metrics['price_dynamics']['volatility_intensity_index']})")
        self.logger.info(f"Volume Breakout: {vol_breakout:.2f}")
        
        # 1. Volatility Expansion (The 'Bang')
        if vol_regime == "EXPANSION":
            self.logger.info("Scanner: [READY] Volatility EXPLOSION/EXPANSION detected.")
            return True
            
        # 2. Squeeze (The 'Gun' before the Bang)
        if vol_regime == "SQUEEZE":
            self.logger.info("Scanner: [READY] Market in SQUEEZE. Intercepting potential breakout.")
            return True
            
        # 3. Volume Breakout (Using Config Threshold)
        vol_threshold = self.config['observer']['regime_volume_breakout_threshold']
        if vol_breakout >= vol_threshold:
            self.logger.info(f"Scanner: [READY] VOLUME breakout detected (>= {vol_threshold}).")
            return True

        # 5. Structural Proximity (Testing POC/VA/VAL)
        topo = metrics['volume_topography']
        anchors_above = topo['anchors_above']
        anchors_below = topo['anchors_below']
        current_price = metrics['price_dynamics']['current_price']
        atr = metrics['price_dynamics']['atr_macro']
        
        # If price is within 0.5 ATR of ANY significant anchor, it's worth it
        for anchor in (anchors_above + anchors_below):
            dist_atr = abs(current_price - anchor['price']) / atr
            if dist_atr < 0.5:
                self.logger.info(f"Scanner: [READY] Proximity to structural {anchor['type']} ({anchor['price']:.2f}) | Dist: {dist_atr:.2f} ATR.")
                return True

        # 6. Liquidation Clusters (Resilient to Null from Binance)
        sentiment = metrics['sentiment_signals']
        clusters = sentiment['liquidation_clusters']
        if clusters:
            liq_count = len(clusters)
            self.logger.info(f"Scanner: [READY] {liq_count} Liquidation clusters detected nearby (Magnet effect).")
            return True

        self.logger.info("Scanner: [PASS] Market lacks sufficient structural catalyst.")
        self.logger.info("-" * 40)
        return False
