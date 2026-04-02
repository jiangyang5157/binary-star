import os
from datetime import datetime, timezone
from typing import Dict, Any

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.topography_engine import ObserverAgent, ObserverConfig
from src.analyzer.chart_generator import ChartGenerator
from src.utils.path_utils import resolve_project_root

class TopographyRecon:
    """Orchestrates market reconnaissance and topography mapping."""
    def __init__(self, config_dict: Dict[str, Any], data_root: str, logger):
        self.config = config_dict
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.logger = logger
        self.binance_client = BinanceFuturesClient()
        self.chart_gen = ChartGenerator(
            output_dir=os.path.join(self.data_root, "klines")
        )

    def observe_market(self, symbol: str) -> Dict[str, Any]:
        """Scans market topography and returns physical evidence (POC, VAH, VAL, CVD)."""
        self.logger.info(f"TopographyRecon: Mapping market topography for {symbol} at {datetime.now(timezone.utc)}...")
        
        try:
            obs_config = ObserverConfig.from_dict(self.config)
            observer = ObserverAgent(
                config=obs_config,
                symbol=symbol,
                data_root=self.data_root,
                binance_client=self.binance_client,
                chart_generator=self.chart_gen
            )
            
            observation = observer.observe()
            return {"symbol": symbol, "observation": observation}
        finally:
            self.binance_client.close()
