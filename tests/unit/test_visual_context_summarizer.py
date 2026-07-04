# tests/unit/test_visual_context_summarizer.py
import pandas as pd
import numpy as np
import pytest
from src.analyzer.visual_context_summarizer import VisualContextSummarizer


def make_test_df(close=97234.5, atr_val=1240.3, bars=20):
    """Deterministic OHLCV DataFrame matching ChartGenerator input format."""
    np.random.seed(42)
    base = close - atr_val * 3
    dates = pd.date_range("2026-07-04 08:00", periods=bars, freq="1h")
    data = []
    for i in range(bars):
        o = base + np.random.randn() * atr_val * 0.3
        h = o + abs(np.random.randn()) * atr_val * 0.5
        l = o - abs(np.random.randn()) * atr_val * 0.5
        c_val = o + np.random.randn() * atr_val * 0.2
        v = abs(np.random.randn()) * 5000 + 10000
        a = atr_val + np.random.randn() * 50
        data.append({
            "open": o, "high": h, "low": l, "close": c_val,
            "volume": v, "atr": a,
        })
    df = pd.DataFrame(data, index=dates)
    df.iloc[-1, df.columns.get_loc("close")] = close
    return df


def make_profile_data():
    return {
        "poc": 96810.0,
        "vah": 97812.0,
        "val": 96102.3,
        "volume_span_atr": 1.38,
        "nearest_hvn_dist_atr": 0.44,
        "nearest_lvn_dist_atr": 0.82,
        "anchors_above": [
            {"price": 98201.5, "volume": 18500.0, "strength": 0.91, "type": "HVN"},
        ],
        "anchors_below": [
            {"price": 96810.0, "volume": 24500.0, "strength": 0.94, "type": "HVN"},
            {"price": 96450.8, "volume": 15200.0, "strength": 0.76, "type": "HVN"},
        ],
        "profile_data": [
            {"price": p, "volume": v}
            for p, v in [(95500, 8000), (95800, 12000), (96100, 18000),
                         (96400, 22000), (96700, 28000), (97000, 18000),
                         (97300, 12000), (97600, 9000), (97900, 7000),
                         (98200, 5000), (98500, 3000)]
        ],
    }


def make_liquidations():
    return {
        "long_liquidation": [
            {"price": 95780.5, "intensity": 0.88},
            {"price": 95230.0, "intensity": 0.35},
        ],
        "short_liquidation": [
            {"price": 97950.2, "intensity": 0.82},
            {"price": 98430.1, "intensity": 0.31},
        ],
    }


class TestVisualContextSummarizer:

    def setup_method(self):
        self.summarizer = VisualContextSummarizer()

    def test_generate_returns_string_with_all_sections(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert isinstance(result, str)
        for section in ["PRICE LADDER", "CANDLESTICK PANORAMA",
                        "VOLUME-AT-TIME PROFILE", "VOLUME PROFILE TOPOGRAPHY",
                        "LIQUIDATION LANDSCAPE", "KEY LEVELS REFERENCE"]:
            assert section in result, f"Missing section: {section}"

    def test_price_ladder_contains_all_levels(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        for price_str in ["96810.0", "97812.0", "96102.3", "98201.5",
                          "96450.8", "95780.5", "97950.2", "98430.1", "95230.0"]:
            assert price_str in result, f"Missing price: {price_str}"
        assert "97234.5" in result
        assert "CURRENT PRICE" in result

    def test_distance_percent_correct(self):
        """POC at 96810.0 with current 97234.5 = −0.44%"""
        df = make_test_df(close=97234.5)
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert "−0.44%" in result

    def test_candle_body_calculation(self):
        """body = abs(close - open), verified on last bar."""
        df = make_test_df(bars=6)
        df.iloc[-1, df.columns.get_loc("open")] = 99700.0
        df.iloc[-1, df.columns.get_loc("high")] = 99780.0
        df.iloc[-1, df.columns.get_loc("low")] = 97200.0
        df.iloc[-1, df.columns.get_loc("close")] = 97234.5

        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        # body = abs(97234.5 - 99700.0) = 2465.5 → formatted to "2466" with .0f
        assert "2466" in result

    def test_empty_liquidations_handled(self):
        df = make_test_df()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations={},
            time_interval="1h", atr=1240.3,
        )
        assert "LIQUIDATION LANDSCAPE" in result

    def test_empty_df_returns_minimal(self):
        df = pd.DataFrame()
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=make_profile_data(),
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert isinstance(result, str)
        assert "no data" in result.lower()

    def test_profile_shape_b_shaped(self):
        """POC positioned in lower VA → b-shaped."""
        df = make_test_df()
        pd_ = make_profile_data()
        pd_["poc"] = 96500.0  # (96500-96102.3)/(97812-96102.3) = 23.3% from VAL
        result = self.summarizer.generate(
            symbol="BTCUSDT", df=df,
            profile_data=pd_,
            liquidations=make_liquidations(),
            time_interval="1h", atr=1240.3,
        )
        assert "b-shaped" in result.lower()
