import pandas as pd
import numpy as np
from typing import Dict, List, Any

class VolumeProfileAnalyzer:
    """
    Analyzes K-line data to calculate the Volume Profile.
    Essential for identifying Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
    """
    def __init__(self, value_area_pct: float = 0.70, bins: int = 50):
        self.value_area_pct = value_area_pct
        self.bins = bins

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
        
        return df

    def calculate_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates the Volume Profile over the provided DataFrame.
        """
        if df.empty:
            return {}

        min_price = df['low'].min()
        max_price = df['high'].max()
        
        # Create price bins
        price_bins = np.linspace(min_price, max_price, self.bins + 1)
        
        # We will distribute the volume of each candle across the bins it spans.
        # For simplicity in this iteration, we assign the volume to the bin containing the 'typical price'
        # Typical price = (High + Low + Close) / 3
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        
        # Digitize the typical prices into our bins
        df['bin'] = np.digitize(df['typical_price'], price_bins)
        
        # Summarize volume per bin
        profile = df.groupby('bin')['volume'].sum().reset_index()
        
        # Map bin indices back to price ranges
        profile['price'] = profile['bin'].apply(lambda x: price_bins[x-1] if x > 0 else price_bins[0])
        
        # Find Point of Control (POC)
        poc_idx = profile['volume'].idxmax()
        poc_price = profile.loc[poc_idx, 'price']
        poc_volume = profile.loc[poc_idx, 'volume']
        
        # Calculate Value Area
        total_volume = profile['volume'].sum()
        value_area_volume = total_volume * self.value_area_pct
        
        # Sort bins by volume descending to build the value area
        sorted_profile = profile.sort_values(by='volume', ascending=False)
        
        cumulative_volume = 0
        value_area_bins = []
        for idx, row in sorted_profile.iterrows():
            cumulative_volume += row['volume']
            value_area_bins.append(row['price'])
            if cumulative_volume >= value_area_volume:
                break
                
        vah = max(value_area_bins)
        val = min(value_area_bins)
        
        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "profile_data": profile[['price', 'volume']].to_dict('records')
        }
