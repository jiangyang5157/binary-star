import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from google import genai
from google.genai import types

from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.sentiment import SentimentFetcher
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.market_regime import MarketRegimeAnalyzer
from src.analyzer.chart_generator import ChartGenerator
from src.utils.agent_utils import load_prompt
from src.utils.datetime_utils import format_datetime
from src.utils.path_utils import find_project_root

logger = logging.getLogger(__name__)

class ObserverAgent:
    """
    Observer Agent (Data Service).
    Responsible for:
    1. Fetching raw market data (Klines, Sentiment, Liquidations).
    2. Calculating technical indicators (VP, BB, KC, ATR, etc.).
    3. Generating visual charts.
    4. Generating 'Semantic Observations' using Gemini Flash.
    """
    
    def __init__(self, config: Dict[str, Any], symbol: str, api_key: str):
        self.config = config
        self.symbol = symbol
            
        observer_config = config['observer']
        strategy_config = config['strategy']
        paths_config = config['paths']

        self.vp_analyzer = VolumeProfileAnalyzer(
            value_area_pct=strategy_config['vp_value_area_pct'],
            vol_profile_bins=strategy_config['vp_bins'],
            atr_window=strategy_config['atr_window'],
            hvn_count=observer_config['hvn_count'],
            lvn_count=observer_config['lvn_count'],
            hvn_sensitivity=observer_config['hvn_sensitivity'],
            lvn_sensitivity=observer_config['lvn_sensitivity'],
            node_min_separation=observer_config['node_min_separation']
        )
        self.regime_analyzer = MarketRegimeAnalyzer(
            bb_window=strategy_config['bb_window'],
            bb_std=strategy_config['bb_std'],
            kc_window=strategy_config['kc_window'],
            kc_mult=strategy_config['kc_mult'],
            vol_ma_window=strategy_config['vol_ma_window'],
            trend_intensity_threshold=strategy_config['trend_intensity_threshold']
        )
        
        self.binance_fetcher = BinanceDataFetcher()
        self.sentiment_fetcher = SentimentFetcher()

        project_root = find_project_root()
        self.chart_generator = ChartGenerator(
            output_dir=os.path.join(
                project_root, 
                paths_config['data_dir'], 
                paths_config['images_dir']
            )
        )
        
        self.prompt_path = os.path.join(
            project_root,
            observer_config['prompt_path']
        )
        
        if not api_key:
            raise ValueError("ObserverAgent: api_key is required for initialization")
            
        self.client = genai.Client(api_key=api_key)
        self.model_name = observer_config['model']

    def observe(self, timestamp_utc: Optional[datetime] = datetime.now(timezone.utc), data_dir: Optional[str] = None) -> Dict[str, Any]:
        logger.info(f"ObserverAgent: Starting observation for {self.symbol} at {timestamp_utc}")
        
        prediction_config = self.config['prediction']
        paths_config = self.config['paths']

        raw_data = self._fetch_raw_data(timestamp_utc)
        
        metrics = self._build_metrics(raw_data)
        
        chart_paths = self._generate_charts(
            raw_data, 
            metrics, 
            data_dir=data_dir or paths_config['data_dir'],
            timestamp=timestamp_utc
        )
        
        observations, final_timestamp = self._generate_semantic_observations(metrics, chart_paths, timestamp_utc)
        
        macro_timeframe = prediction_config['macro_timeframe']
        micro_timeframe = prediction_config['micro_timeframe']
        
        logger.info("Observer: Observation cycle complete.")
        return {
            "symbol": self.symbol,
            "timestamp": f"{final_timestamp}Z",
            "macro_timeframe": {
                "interval": macro_timeframe['interval'],
                "limit": macro_timeframe['limit']
            },
            "micro_timeframe": {
                "interval": micro_timeframe['interval'],
                "limit": micro_timeframe['limit']
            },
            "chart_path": {
                "snapshot_macro": chart_paths.get("macro_timeframe"),
                "snapshot_micro": chart_paths.get("micro_timeframe")
            },
            "metrics": metrics,
            "observations": observations
        }

    def _get_ms_from_interval(self, interval: str) -> int:
        """Converts interval strings (1m, 15m, 1h, 1d) to milliseconds."""
        unit = interval[-1]
        val = int(interval[:-1])
        mapping = {"m": 60, "h": 3600, "d": 86400}
        return val * mapping.get(unit, 60) * 1000

    def _fetch_raw_data(self, timestamp_utc: Optional[datetime] = datetime.now(timezone.utc)) -> Dict[str, Any]:
        fetch_kwargs = {}
        fetch_kwargs['endTime'] = int(timestamp_utc.timestamp() * 1000)
        now_ts = fetch_kwargs.get('endTime')

        prediction_config = self.config['prediction']
        macro_timeframe = prediction_config['macro_timeframe']
        micro_timeframe = prediction_config['micro_timeframe']
        strategy_config = self.config['strategy']
        
        klines_macro = self.binance_fetcher.fetch_historical_klines(
            self.symbol, macro_timeframe['interval'], macro_timeframe['limit'], **fetch_kwargs
        )
        klines_micro = self.binance_fetcher.fetch_historical_klines(
            self.symbol, micro_timeframe['interval'], micro_timeframe['limit'], **fetch_kwargs
        )
        
        hist_kwargs_macro = fetch_kwargs.copy()
        hist_kwargs_macro['endTime'] = now_ts - self._get_ms_from_interval(macro_timeframe['interval'])
        oi_hist_macro = self.sentiment_fetcher.fetch_open_interest(self.symbol, macro_timeframe['interval'], **hist_kwargs_macro)
        
        hist_kwargs_micro = fetch_kwargs.copy()
        hist_kwargs_micro['endTime'] = now_ts - self._get_ms_from_interval(micro_timeframe['interval'])
        oi_hist_micro = self.sentiment_fetcher.fetch_open_interest(self.symbol, micro_timeframe['interval'], **hist_kwargs_micro)
        
        ls_ratio_macro = self.sentiment_fetcher.fetch_long_short_ratio(self.symbol, macro_timeframe['interval'], limit=1, **fetch_kwargs)
        ls_ratio_micro = self.sentiment_fetcher.fetch_long_short_ratio(self.symbol, micro_timeframe['interval'], limit=1, **fetch_kwargs)
        
        oi_current = self.sentiment_fetcher.fetch_open_interest(self.symbol, micro_timeframe['interval'], **fetch_kwargs)
        liquidations = self.binance_fetcher.fetch_liquidations(self.symbol, limit=strategy_config['liquidation_fetch_limit'])
        
        return {
            "klines_macro": klines_macro,
            "klines_micro": klines_micro,
            "oi_hist_macro": oi_hist_macro,
            "oi_hist_micro": oi_hist_micro,
            "ls_ratio_macro": ls_ratio_macro,
            "ls_ratio_micro": ls_ratio_micro,
            "open_interest": oi_current,
            "liquidations": liquidations
        }

    def _build_metrics(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        strategy_config = self.config['strategy']
        observer_config = self.config['observer']

        df_macro = self.vp_analyzer.process_klines(raw_data['klines_macro'])
        df_micro = self.vp_analyzer.process_klines(raw_data['klines_micro'])
        
        profile = self.vp_analyzer.calculate_profile(df_macro)
        nodes = self.vp_analyzer.find_significant_nodes(profile)
        regime = self.regime_analyzer.analyze(df_macro)
        
        lookback = strategy_config['order_flow_lookback_bars']
        total_delta = 0
        if raw_data['klines_micro']:
            recent = raw_data['klines_micro'][-lookback:]
            for k in recent:
                vol = float(k[5])
                taker_buy = float(k[9])
                total_delta += (taker_buy - (vol - taker_buy))

        vol_window = strategy_config['vol_ma_window']
        vol_ratio = 1.0
        if raw_data['klines_macro']:
            recent_vols = [float(k[5]) for k in raw_data['klines_macro'][-vol_window:]]
            if recent_vols:
                avg_vol = sum(recent_vols) / len(recent_vols)
                curr_vol = float(raw_data['klines_macro'][-1][5])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

        # ATR Skewness (Wick Pressure)
        last_k = raw_data['klines_macro'][-1]
        k_h, k_l, k_c = float(last_k[2]), float(last_k[3]), float(last_k[4])
        skewness = (k_c - k_l) / (k_h - k_l) if (k_h - k_l) > 0 else 0.5

        # Structural Proximity (Distance to POC/VAH/VAL in ATR units)
        curr_price = df_macro['close'].iloc[-1]
        atr_m = df_macro['atr'].iloc[-1]
        
        def get_dist_atr(target_price):
            if not target_price or not atr_m: return None
            return f"{((curr_price - target_price) / atr_m):.2f}"

        # Nearest Structural Nodes (Structural Anchors) - Inclusion of Count (Density)
        node_count = observer_config['structural_anchor_count']
        all_nodes = []
        for n in nodes['hvn']: all_nodes.append({**n, "type": "HVN"})
        for n in nodes['lvn']: all_nodes.append({**n, "type": "LVN"})
        
        above = sorted([n for n in all_nodes if n['price'] > curr_price], key=lambda x: x['price'])[:node_count]
        below = sorted([n for n in all_nodes if n['price'] < curr_price], key=lambda x: x['price'], reverse=True)[:node_count]

        # OI Delta % (Multi-Timeframe)
        oi_current = 0
        oi_delta_macro = None
        oi_delta_micro = None
        
        if raw_data['open_interest'] and 'openInterest' in raw_data['open_interest']:
            oi_current = float(raw_data['open_interest']['openInterest'])
            
            # Macro Delta
            if raw_data.get('oi_hist_macro') and 'openInterest' in raw_data['oi_hist_macro']:
                hist_oi_m = float(raw_data['oi_hist_macro']['openInterest'])
                if hist_oi_m > 0:
                    delta_m = ((oi_current - hist_oi_m) / hist_oi_m) * 100
                    oi_delta_macro = f"{delta_m:+.2f}%"
            
            # Micro Delta
            if raw_data.get('oi_hist_micro') and 'openInterest' in raw_data['oi_hist_micro']:
                hist_oi_n = float(raw_data['oi_hist_micro']['openInterest'])
                if hist_oi_n > 0:
                    delta_n = ((oi_current - hist_oi_n) / hist_oi_n) * 100
                    oi_delta_micro = f"{delta_n:+.2f}%"

        # Liquidations Processing (Null for Failed/Maintenance, Empty list for strictly Zero)
        top_liquidations = None
        if raw_data.get('liquidations') is not None:
            top_liquidations = []
            sorted_liqs = sorted(raw_data['liquidations'], key=lambda x: float(x.get('qty', 0)), reverse=True)
            liq_limit = strategy_config['liquidation_context_limit']
            for l in sorted_liqs[:liq_limit]:
                top_liquidations.append({
                    "side": l.get('side'),
                    "price": float(l.get('price', 0)),
                    "qty": float(l.get('qty', 0)),
                    "time": datetime.fromtimestamp(l.get('time', 0)/1000, tz=timezone.utc).strftime('%H:%M:%S')
                })

        metrics = {
            "price": {
                "current": curr_price,
                "atr_macro": atr_m,
                "atr_micro": df_micro['atr'].iloc[-1],
                "skewness": f"{skewness:.2f}"
            },
            "structural_proximity_atr": {
                "to_poc": get_dist_atr(profile.get('poc')),
                "to_vah": get_dist_atr(profile.get('vah')),
                "to_val": get_dist_atr(profile.get('val'))
            },
            "volume_profile": {
                "poc": profile.get('poc'),
                "vah": profile.get('vah'),
                "val": profile.get('val'),
                "nearest_nodes_above": above,
                "nearest_nodes_below": below,
                "volume_breakout_ratio": f"{vol_ratio:.2f}"
            },
            "regime": regime,
            "sentiment": {
                "open_interest": oi_current,
                "oi_delta_macro": oi_delta_macro,
                "oi_delta_micro": oi_delta_micro,
                "ls_ratio_macro": raw_data['ls_ratio_macro'][0].get('longShortRatio') if raw_data['ls_ratio_macro'] else None,
                "ls_ratio_micro": raw_data['ls_ratio_micro'][0].get('longShortRatio') if raw_data['ls_ratio_micro'] else None,
                "order_flow_delta": f"{total_delta:.4f}",
                "top_liquidations": top_liquidations
            }
        }
        return metrics

    def _generate_charts(self, 
                       raw_data: Dict[str, Any], 
                       metrics: Dict[str, Any],
                       data_dir: str,
                       timestamp: Optional[datetime] = datetime.now(timezone.utc)) -> Dict[str, str]:
        """
        Generates visualized charts for the Macro and Micro timeframes.
        Supports custom output directories and deterministic naming.
        """

        paths_config = self.config['paths']

        # 1. Setup Output Directory
        images_path = os.path.join(data_dir, paths_config['images_dir'])
        os.makedirs(images_path, exist_ok=True)
        
        # 2. Update Generator Output Dir
        self.chart_generator.output_dir = images_path
        
        # 3. Prepare Figure Data (POC/VAH/VAL)
        # Note: ChartGenerator expects profile_data in a specific format
        profile_data_for_chart = metrics['volume_profile'].copy()
        # Use provided timestamp or current
        profile_data_for_chart['timestamp'] = timestamp.isoformat()
        
        # Add full profile data for VAP plot
        profile_data_for_chart['profile_data'] = metrics['volume_profile'].get('profile_data', [])
        
        # 4. Generate Both Timeframes
        # We need to convert raw klines to DataFrames for the generator
        df_macro = self.vp_analyzer.process_klines(raw_data['klines_macro'])
        df_micro = self.vp_analyzer.process_klines(raw_data['klines_micro'])
        
        macro_path = self.chart_generator.generate_chart(
            self.symbol, df_macro, profile_data_for_chart, raw_data['liquidations'], 
            filename_suffix=self.config['prediction']['macro_timeframe']['interval']
        )
        micro_path = self.chart_generator.generate_chart(
            self.symbol, df_micro, profile_data_for_chart, raw_data['liquidations'], 
            filename_suffix=self.config['prediction']['micro_timeframe']['interval']
        )
        
        return {
            "macro_timeframe": macro_path if macro_path else None,
            "micro_timeframe": micro_path if micro_path else None
        }

    def _generate_semantic_observations(self, 
                                       metrics: Dict[str, Any], 
                                       chart_paths: Dict[str, str],
                                       timestamp_utc: Optional[datetime] = datetime.now(timezone.utc)) -> Tuple[Dict[str, str], str]:
        
        prediction_config = self.config['prediction']
        observer_config = self.config['observer']
        
        try:
            from google.genai import types
            macro_tf_interval = prediction_config['macro_timeframe']['interval']
            micro_tf_interval = prediction_config['micro_timeframe']['interval']
            
            prompt_with_context = load_prompt(self.prompt_path)
            
            from src.utils.json_utils import to_json
            prompt = prompt_with_context.format(
                timestamp=format_datetime(timestamp_utc),
                macro_timeframe=to_json(prediction_config['macro_timeframe']),
                micro_timeframe=to_json(prediction_config['micro_timeframe']),
                metrics=to_json(metrics)
            )
            
            contents = []
            
            # 1. Macro Chart
            path_macro = chart_paths['macro_timeframe']
            if path_macro and os.path.exists(path_macro):
                contents.append("[IMAGE: MACRO CHART]")
                with open(path_macro, 'rb') as f:
                    contents.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))

            # 2. Micro Chart
            path_micro = chart_paths['micro_timeframe']
            if path_micro and os.path.exists(path_micro):
                contents.append("[IMAGE: MICRO CHART]")
                with open(path_micro, 'rb') as f:
                    contents.append(types.Part.from_bytes(data=f.read(), mime_type='image/png'))

            # Add prompt text at the end
            contents.append(prompt)
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=observer_config['temperature'],
                    response_mime_type="application/json"
                )
            )

            obs_dict = json.loads(response.text)
            
            section_keys = [
                "structural_proximity",
                "anomaly_detection",
                "regime_delta",
                "macro_topography",
                "micro_execution"
            ]
            for key in section_keys:
                if key not in obs_dict:
                    obs_dict[key] = "AI analysis currently unavailable for this dimension."
            
            return obs_dict, timestamp_utc
        except Exception as e:
            logger.error(f"Failed to generate semantic observations: {e}", exc_info=True)
            return {"error": str(e)}, format_datetime(timestamp_utc)

    def close(self):
        self.binance_fetcher.close()
        self.sentiment_fetcher.close()
