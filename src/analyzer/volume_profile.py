import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from typing import Dict, List, Any

class VolumeProfileAnalyzer:
    """
    Analyzes K-line data to calculate the Volume Profile.
    Essential for identifying Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
    """
    def __init__(self, value_area_pct: float, vol_profile_bins: int, atr_window: int, 
                 hvn_count: int, lvn_count: int, 
                 hvn_sensitivity: float, lvn_sensitivity: float, 
                 min_node_spacing: int):
        self.value_area_pct = value_area_pct
        self.vol_profile_bins = vol_profile_bins
        self.atr_window = atr_window
        self.hvn_count = hvn_count
        self.lvn_count = lvn_count
        self.hvn_sensitivity = hvn_sensitivity
        self.lvn_sensitivity = lvn_sensitivity
        self.min_node_spacing = min_node_spacing

    def process_klines(self, klines_data: List[List[Any]]) -> pd.DataFrame:
        """
        Converts raw Binance Kline data into a usable pandas DataFrame.
        """
        # Binance Kline format:
        # [Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore]
        df = pd.DataFrame(klines_data, columns=[
            "open_time", "open", "high", "low", "close", "volume", 
            "close_time", "quote_volume", "trades", "taker_buy_base", 
            "taker_buy_quote", "ignore"
        ])
        
        # Convert numeric columns
        numeric_cols = ["open", "high", "low", "close", "volume", "taker_buy_base"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        # Convert timestamps
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        
        # Calculate ATR (14-period)
        high_low = df['high'] - df['low']
        high_cp = np.abs(df['high'] - df['close'].shift())
        low_cp = np.abs(df['low'] - df['close'].shift())
        
        df['tr'] = np.maximum(high_low, np.maximum(high_cp, low_cp))
        df['atr'] = df['tr'].rolling(window=self.atr_window).mean()
        
        return df

    def calculate_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates the Volume Profile over the provided DataFrame.
        
        Concept:
        - POC (Point of Control): The price level with the highest traded volume.
        - VAH (Value Area High): The upper boundary of the price range where 70% (default) of volume occurred.
        - VAL (Value Area Low): The lower boundary of the price range where 70% (default) of volume occurred.

        Returns:
            {
                "poc": 74060.80,       # Point of Control：成交量最大的那个价格
                "vah": 75200.00,       # Value Area High：价值区上限
                "val": 73100.00,       # Value Area Low：价值区下限
                "profile_data": [      # 这是一个列表，包含了所有 50 个格子的分布数据，用于绘图
                    {"price": 72500.0, "volume": 120.5},
                    {"price": 72600.0, "volume": 340.2},
                    ... # 总共 50 条记录
                ]
            }
        """
        if df.empty:
            return {}

        # 1. Determine the global price range for the current window
        min_price = df['low'].min()
        max_price = df['high'].max()
        
        # 2. Divide this range into 'bins' (horizontal buckets)
        price_bins = np.linspace(min_price, max_price, self.vol_profile_bins + 1)
        
        # 3. Associate each K-line's volume with its price location.
        # For simplicity, we use 'typical price' (H+L+C)/3 to represent the center of gravity of the candle.
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        
        # 4. Sorting candles into their respective horizontal buckets
        df['bin'] = np.digitize(df['typical_price'], price_bins)
        
        # 5. Summarize volume per bin (Summing up the total volume traded at each price level)
        profile = df.groupby('bin')['volume'].sum().reset_index()
        
        # 6. Map bin indices back to human-readable price values
        profile['price'] = profile['bin'].apply(lambda x: price_bins[x-1] if x > 0 else price_bins[0])
        
        # 7. Identify the Point of Control (POC) - The 'busiest' price level
        poc_idx = profile['volume'].idxmax()
        poc_price = profile.loc[poc_idx, 'price']
        
        # 8. Calculate the Value Area (VA)
        # This identifies where the majority of trading ('fair value') took place.
        total_volume = profile['volume'].sum()
        value_area_volume = total_volume * self.value_area_pct
        
        # We find the value area by sorting bins by volume descending 
        # and accumulating until we reach the target volume percentage (currenlty 70%).
        sorted_profile = profile.sort_values(by='volume', ascending=False)
        
        cumulative_volume = 0
        value_area_bins = []
        for idx, row in sorted_profile.iterrows():
            cumulative_volume += row['volume']
            value_area_bins.append(row['price'])
            if cumulative_volume >= value_area_volume:
                break
                
        # The VAH and VAL are the boundaries of these most active bins
        if not value_area_bins:
            vah, val = poc_price, poc_price
        else:
            vah = max(value_area_bins)
            val = min(value_area_bins)
        
        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "profile_data": profile[['price', 'volume']].to_dict('records') # Full data for charting
        }

    def find_significant_nodes(self, profile_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Identifies High Volume Nodes (HVN) and Low Volume Nodes (LVN) from the profile.
        Returns a structured list with relative strength/vacuum scores.
        """
        data = profile_result.get("profile_data", [])
        poc_price = profile_result.get("poc", 0)
        
        if not data:
            return {"hvn": [], "lvn": []}
            
        volumes = np.array([float(d['volume']) for d in data])
        prices = np.array([float(d['price']) for d in data])
        max_vol = volumes.max() if volumes.size > 0 else 1.0
        
        # Simple peak/trough detection
        from scipy.signal import find_peaks
        
        # HVNs: Local maxima with prominence check
        hvn_indices, _ = find_peaks(volumes, prominence=max_vol * self.hvn_sensitivity, distance=self.min_node_spacing)
        hvns = []
        for i in hvn_indices:
            hvns.append({
                "price": round(float(prices[i]), 2),
                "strength": round(float(volumes[i] / max_vol), 3)
            })
        hvns = sorted(hvns, key=lambda x: x['strength'], reverse=True)
        
        # LVNs: Local minima (inverted peaks)
        lvn_indices, _ = find_peaks(-volumes, prominence=max_vol * self.lvn_sensitivity, distance=self.min_node_spacing)
        lvns = []
        for i in lvn_indices:
            lvns.append({
                "price": round(float(prices[i]), 2),
                "vacuum_score": round(float(volumes[i] / max_vol), 3)
            })
        lvns = sorted(lvns, key=lambda x: x['vacuum_score'])
        
        return {
            "hvn": hvns[:self.hvn_count],
            "lvn": lvns[:self.lvn_count]
        }
