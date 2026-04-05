import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.market_observer import MarketObserver, MarketObserverConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.path_utils import resolve_project_root

class TopographyEngine:
    """Orchestrates market reconnaissance and topography reconstruction."""
    def __init__(self, config_dict: Dict[str, Any], data_root: str, logger):
        self.config = config_dict
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.logger = logger
        self.binance_client = BinanceFuturesClient()
        
        # Parse config early to inject visual parameters
        obs_config = MarketObserverConfig.from_dict(config_dict)
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(self.data_root, "klines"),
            vol_profile_width_ratio=obs_config.vol_profile_width_ratio,
            render_dpi=obs_config.render_dpi
        )

    def reconstruct(self, symbol: str, at_time: Optional[datetime] = None, dispatch_email: bool = False) -> Dict[str, Any]:
        """Scans market topography and returns physical evidence (POC, VAH, VAL, CVD)."""
        at_time = at_time or datetime.now(timezone.utc)
        self.logger.info(f"TopographyEngine: Reconstructing market topography for {symbol} at {at_time}...")
        
        try:
            obs_config = MarketObserverConfig.from_dict(self.config)
            observer = MarketObserver(
                config=obs_config,
                symbol=symbol,
                data_root=self.data_root,
                binance_client=self.binance_client,
                chart_generator=self.chart_gen
            )
            
            observation = observer.observe(timestamp=at_time)
            
            if dispatch_email:
                from src.infrastructure.notifications.email_notifier import SessionNotifier
                notifier = SessionNotifier(data_root=self.data_root)
                
                # Mock a strategy result for the notifier
                strat_result = {
                    "observation": observation,
                    "final_decision": {"opinion": "MARKET_SCAN", "confidence": 100, "reasoning": "Manual Market Reconstruction requested via CLI."}
                }
                
                # Save local and dispatch audit
                notifier.notify_market_recon(symbol, strat_result, save_local=True, dispatch_email=True)
                self.logger.info(f"TopographyEngine: Market audit report dispatched for {symbol}.")

            return {"symbol": symbol, "observation": observation}
        finally:
            self.binance_client.close()
