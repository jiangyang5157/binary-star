import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from google import genai
from google.genai import types

# Technical components
from src.data_fetcher.binance_client import BinanceDataFetcher
from src.data_fetcher.sentiment import SentimentFetcher
from src.analyzer.volume_profile import VolumeProfileAnalyzer
from src.analyzer.market_regime import MarketRegimeAnalyzer
from src.analyzer.chart_generator import ChartGenerator
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
    
    def __init__(self, config: Dict[str, Any], symbol: str):
        self.config = config
        self.symbol = symbol
        
        # Initialize fetchers
        self.binance_fetcher = BinanceDataFetcher()
        self.sentiment_fetcher = SentimentFetcher()
        
        # Initialize analyzers
        if 'observer' not in config:
            raise ValueError("Missing 'observer' section in config.yaml")
            
        obs_cfg = config['observer']
        self.vp_analyzer = VolumeProfileAnalyzer(
            value_area_pct=config['strategy']['vp_value_area_pct'],
            vol_profile_bins=config['strategy']['vp_bins'],
            atr_window=config['strategy']['atr_window'],
            hvn_count=obs_cfg['hvn_count'],
            lvn_count=obs_cfg['lvn_count'],
            hvn_sensitivity=obs_cfg['hvn_sensitivity'],
            lvn_sensitivity=obs_cfg['lvn_sensitivity'],
            node_min_separation=obs_cfg['node_min_separation']
        )
        self.regime_analyzer = MarketRegimeAnalyzer(
            bb_window=config['strategy']['bb_window'],
            bb_std=config['strategy']['bb_std'],
            kc_window=config['strategy']['kc_window'],
            kc_mult=config['strategy']['kc_mult'],
            vol_ma_window=config['strategy']['vol_ma_window'],
            trend_intensity_threshold=config['strategy']['trend_intensity_threshold']
        )
        
        # Initialize Chart Generator
        project_root = find_project_root()
        self.chart_generator = ChartGenerator(
            output_dir=os.path.join(
                project_root, 
                config['paths']['base_dir'], 
                config['paths']['images_dir']
            )
        )
        
        # Resolve Prompt Path
        self.prompt_path = os.path.join(
            project_root,
            config['observer']['prompt_path']
        )
        # Initialize GenAI client for Semantic Observations
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)
            self.model_name = config['observer']['model']
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client: {e}")
            self.client = None

    def observe(self, override_timestamp: Optional[datetime] = None, base_data_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Main entry point for observing the market state.
        Now supports historical observation for simulation/backtesting.
        """
        logger.info(f"Observer: Starting observation for {self.symbol} at {override_timestamp or 'current time'}")
        
        # 1. Fetch Data
        raw_data = self._fetch_all_data(override_timestamp)
        
        # 2. Process Indicators
        processed_metrics = self._process_indicators(raw_data)
        
        # 3. Generate Charts (Pass base_data_dir and timestamp for naming)
        chart_paths = self._generate_charts(
            raw_data, 
            processed_metrics, 
            base_data_dir=base_data_dir,
            naming_ts=override_timestamp
        )
        
        # 4. Generate Semantic Observations (AI Layer)
        # Use the specific timestamp or now for the prompt
        ts_for_ai = override_timestamp or datetime.now(timezone.utc)
        observations, final_ts = self._generate_semantic_observations(processed_metrics, chart_paths, ts_for_ai)
        
        # 5. Construct Final Structured Output
        macro_cfg = self.config['prediction']['macro_timeframe']
        micro_cfg = self.config['prediction']['micro_timeframe']
        
        logger.info("Observer: Observation cycle complete.")
        return {
            "symbol": self.symbol,
            "timestamp": f"{final_ts}Z",
            "macro_timeframe": {
                "interval": macro_cfg['interval'],
                "limit": macro_cfg['limit']
            },
            "micro_timeframe": {
                "interval": micro_cfg['interval'],
                "limit": micro_cfg['limit']
            },
            "chart_path": {
                "snapshot_macro": chart_paths.get("macro_timeframe"),
                "snapshot_micro": chart_paths.get("micro_timeframe")
            },
            "metrics": processed_metrics,
            "observations": observations
        }

    def _get_ms_from_interval(self, interval: str) -> int:
        """Converts interval strings (1m, 15m, 1h, 1d) to milliseconds."""
        unit = interval[-1]
        val = int(interval[:-1])
        mapping = {"m": 60, "h": 3600, "d": 86400}
        return val * mapping.get(unit, 60) * 1000

    def _fetch_all_data(self, override_timestamp: Optional[datetime]) -> Dict[str, Any]:
        fetch_kwargs = {}
        if override_timestamp:
            fetch_kwargs['endTime'] = int(override_timestamp.timestamp() * 1000)
            
        macro_cfg = self.config['prediction']['macro_timeframe']
        micro_cfg = self.config['prediction']['micro_timeframe']
        
        # 1. Klines
        klines_macro = self.binance_fetcher.fetch_historical_klines(
            self.symbol, macro_cfg['interval'], macro_cfg['limit'], **fetch_kwargs
        )
        klines_micro = self.binance_fetcher.fetch_historical_klines(
            self.symbol, micro_cfg['interval'], micro_cfg['limit'], **fetch_kwargs
        )
        
        # 2. Open Interest (Current & 2 Historical Anchors)
        oi_current = self.sentiment_fetcher.fetch_open_interest(self.symbol, micro_cfg['interval'], **fetch_kwargs)
        
        now_ts = fetch_kwargs.get('endTime') or int(datetime.now(timezone.utc).timestamp() * 1000)
        
        # Macro OI Delta Anchor
        hist_kwargs_macro = fetch_kwargs.copy()
        hist_kwargs_macro['endTime'] = now_ts - self._get_ms_from_interval(macro_cfg['interval'])
        oi_hist_macro = self.sentiment_fetcher.fetch_open_interest(self.symbol, macro_cfg['interval'], **hist_kwargs_macro)
        
        # Micro OI Delta Anchor
        hist_kwargs_micro = fetch_kwargs.copy()
        hist_kwargs_micro['endTime'] = now_ts - self._get_ms_from_interval(micro_cfg['interval'])
        oi_hist_micro = self.sentiment_fetcher.fetch_open_interest(self.symbol, micro_cfg['interval'], **hist_kwargs_micro)
        
        # 3. Ratios & Liquidations
        ls_ratio = self.sentiment_fetcher.fetch_long_short_ratio(self.symbol, macro_cfg['interval'], limit=1, **fetch_kwargs)
        liq_limit = self.config['strategy']['liquidation_fetch_limit']
        liquidations = self.binance_fetcher.fetch_liquidations(self.symbol, limit=liq_limit)
        
        return {
            "klines_macro": klines_macro,
            "klines_micro": klines_micro,
            "open_interest": oi_current,
            "oi_hist_macro": oi_hist_macro,
            "oi_hist_micro": oi_hist_micro,
            "ls_ratio": ls_ratio,
            "liquidations": liquidations
        }

    def _process_indicators(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        df_macro = self.vp_analyzer.process_klines(raw_data['klines_macro'])
        df_micro = self.vp_analyzer.process_klines(raw_data['klines_micro'])
        
        # Volume Profile from Macro
        profile = self.vp_analyzer.calculate_profile(df_macro)
        nodes = self.vp_analyzer.find_significant_nodes(profile)
        
        # Market Regime from Macro
        regime = self.regime_analyzer.analyze(df_macro)
        
        # Order Flow Delta from Micro
        lookback = self.config['strategy']['order_flow_lookback_bars']
        total_delta = 0
        if raw_data['klines_micro']:
            recent = raw_data['klines_micro'][-lookback:]
            for k in recent:
                vol = float(k[5])
                taker_buy = float(k[9])
                total_delta += (taker_buy - (vol - taker_buy))

        # Volume Breakout Ratio (Current Vol vs Window Median)
        vol_window = self.config['strategy']['vol_ma_window']
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
        node_count = self.config['observer']['structural_anchor_count']
        all_nodes = []
        for n in nodes['hvn']: all_nodes.append({**n, "type": "HVN"})
        for n in nodes['lvn']: all_nodes.append({**n, "type": "LVN"})
        
        above = sorted([n for n in all_nodes if n['price'] > curr_price], key=lambda x: x['price'])[:node_count]
        below = sorted([n for n in all_nodes if n['price'] < curr_price], key=lambda x: x['price'], reverse=True)[:node_count]

        # OI Delta % (Multi-Timeframe)
        oi_val = 0
        oi_delta_macro = None
        oi_delta_micro = None
        
        if raw_data['open_interest'] and 'openInterest' in raw_data['open_interest']:
            oi_val = float(raw_data['open_interest']['openInterest'])
            
            # Macro Delta
            if raw_data.get('oi_hist_macro') and 'openInterest' in raw_data['oi_hist_macro']:
                hist_oi_m = float(raw_data['oi_hist_macro']['openInterest'])
                if hist_oi_m > 0:
                    delta_m = ((oi_val - hist_oi_m) / hist_oi_m) * 100
                    oi_delta_macro = f"{delta_m:+.2f}%"
            
            # Micro Delta
            if raw_data.get('oi_hist_micro') and 'openInterest' in raw_data['oi_hist_micro']:
                hist_oi_n = float(raw_data['oi_hist_micro']['openInterest'])
                if hist_oi_n > 0:
                    delta_n = ((oi_val - hist_oi_n) / hist_oi_n) * 100
                    oi_delta_micro = f"{delta_n:+.2f}%"

        # Liquidations Processing (Null for Failed/Maintenance, Empty list for strictly Zero)
        top_liquidations = None
        if raw_data.get('liquidations') is not None:
            top_liquidations = []
            sorted_liqs = sorted(raw_data['liquidations'], key=lambda x: float(x.get('qty', 0)), reverse=True)
            liq_limit = self.config['strategy']['liquidation_context_limit']
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
                "oi": oi_val,
                "oi_delta_macro": oi_delta_macro,
                "oi_delta_micro": oi_delta_micro,
                "ls_ratio": raw_data['ls_ratio'][0].get('longShortRatio') if raw_data['ls_ratio'] else None,
                "order_flow_delta": f"{total_delta:.4f}",
                "top_liquidations": top_liquidations
            }
        }
        return metrics

    def _generate_charts(self, 
                       raw_data: Dict[str, Any], 
                       metrics: Dict[str, Any],
                       base_data_dir: Optional[str] = None,
                       naming_ts: Optional[datetime] = None) -> Dict[str, str]:
        """
        Generates visualized charts for the Macro and Micro timeframes.
        Supports custom output directories and deterministic naming.
        """
        # 1. Setup Output Directory
        data_root = base_data_dir or self.config['paths']['data_dir']
        images_subdir = self.config['paths']['images_dir']
        images_path = os.path.join(data_root, images_subdir)
        os.makedirs(images_path, exist_ok=True)
        
        # 2. Update Generator Output Dir
        self.chart_generator.output_dir = images_path
        
        # 3. Prepare Figure Data (POC/VAH/VAL)
        # Note: ChartGenerator expects profile_data in a specific format
        profile_data_for_chart = metrics['volume_profile'].copy()
        # Use provided timestamp or current
        ts_for_naming = naming_ts or datetime.now(timezone.utc)
        profile_data_for_chart['timestamp'] = ts_for_naming.isoformat()
        
        # Add full profile data for VAP plot
        profile_data_for_chart['profile_data'] = metrics['volume_profile'].get('profile_data', [])
        
        # 4. Generate Both Timeframes
        # We need to convert raw klines to DataFrames for the generator
        df_macro = self.vp_analyzer.process_klines(raw_data['klines_macro'])
        df_micro = self.vp_analyzer.process_klines(raw_data['klines_micro'])
        
        m_path = self.chart_generator.generate_chart(
            self.symbol, df_macro, profile_data_for_chart, raw_data['liquidations'], 
            filename_suffix=self.config['prediction']['macro_timeframe']['interval']
        )
        n_path = self.chart_generator.generate_chart(
            self.symbol, df_micro, profile_data_for_chart, raw_data['liquidations'], 
            filename_suffix=self.config['prediction']['micro_timeframe']['interval']
        )
        
        return {
            "macro_timeframe": m_path if m_path else None,
            "micro_timeframe": n_path if n_path else None
        }

    def _generate_semantic_observations(self, 
                                       metrics: Dict[str, Any], 
                                       chart_paths: Dict[str, str],
                                       naming_ts: Optional[datetime] = None) -> Tuple[Dict[str, str], str]:
        """
        Generates semantic insights via Multimodal Perception (Gemini).
        """
        if not self.client:
            return {"error": "AI Observation layer disabled (No API Key)."}, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            
        try:
            from google.genai import types
            macro_tf_interval = self.config['prediction']['macro_timeframe']['interval']
            micro_tf_interval = self.config['prediction']['micro_timeframe']['interval']
            
            # Read and format prompt
            with open(self.prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            from src.utils.json_utils import to_json
            
            # Use naming_ts for consistency
            ts_actual = naming_ts or datetime.now(timezone.utc)
            timestamp_utc = ts_actual.strftime('%Y-%m-%d %H:%M:%S')
            
            prompt = prompt_template.format(
                timestamp=timestamp_utc,
                macro_timeframe=to_json(self.config['prediction']['macro_timeframe']),
                micro_timeframe=to_json(self.config['prediction']['micro_timeframe']),
                metrics=to_json(metrics)
            )
            
            # Prepare Multi-modal contents
            contents = []
            
            # Interleave semantic labels with chart images
            timeframe_map = {
                "macro_timeframe": "[IMAGE: MACRO CHART]",
                "micro_timeframe": "[IMAGE: MICRO CHART]"
            }
            
            for key in ["macro_timeframe", "micro_timeframe"]:
                path = chart_paths.get(key)
                if path and os.path.exists(path):
                    # Add semantic label
                    contents.append(timeframe_map[key])
                    # Add image part
                    with open(path, 'rb') as f:
                        image_bytes = f.read()
                    contents.append(types.Part.from_bytes(data=image_bytes, mime_type='image/png'))
            
            # Add prompt text at the end
            contents.append(prompt)
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=self.config['observer']['temperature'],
                    response_mime_type="application/json"
                )
            )
            
            # Robustly extract text
            text = response.text or ""
            if not text:
                # Fallback for models that might return non-text parts but have a text attribute that fails
                try:
                    text = "".join([part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')])
                except:
                    text = ""

            try:
                # Direct JSON parsing from the AI response
                obs_dict = json.loads(text)
                
                # Robustness check for required keys
                section_keys = [
                    "structural_proximity",
                    "regime_delta",
                    "macro_topography",
                    "micro_execution",
                    "anomaly_detection"
                ]
                for key in section_keys:
                    if key not in obs_dict:
                        obs_dict[key] = "[MISSING DATA]"
                
                return obs_dict, timestamp_utc
            except Exception as parse_err:
                logger.error(f"Observer: JSON parsing failed: {parse_err}")
                # Fallback: if it's not JSON, return the raw text in an error field
                return {
                    "error": "JSON_PARSE_FAILURE",
                    "raw_response": response.text
                }, timestamp_utc
        except Exception as e:
            logger.error(f"Failed to generate semantic observations: {e}")
            return {"error": f"Error generating observations: {str(e)}"}, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    def close(self):
        self.binance_fetcher.close()
        self.sentiment_fetcher.close()
