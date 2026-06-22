import datetime
import random
from typing import List, Dict, Any
from src.infrastructure.exchange.models import KlineData

class MockDataFactory:
    """Universal generator for deterministic test data."""

    @staticmethod
    def create_mock_klines(count: int = 100, trend: str = "bullish",
                           base_price: float = 60000.0) -> List[KlineData]:
        """Deterministic simulated Binance klines for testing."""
        rng = random.Random(42)  # fixed seed for reproducibility
        now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        interval_ms = 15 * 60 * 1000  # 15m

        drift_per_bar = 50.0 if trend == "bullish" else -50.0
        klines = []
        for i in range(count):
            open_ts = now_ts - (count - i) * interval_ms
            close_ts = open_ts + interval_ms - 1
            noise = rng.uniform(-20, 20)
            open_p = base_price + (i * drift_per_bar) + noise
            close_p = open_p + drift_per_bar + rng.uniform(-10, 10)
            high_p = max(open_p, close_p) + rng.uniform(5, 15)
            low_p = min(open_p, close_p) - rng.uniform(5, 15)
            klines.append(KlineData(
                open_time=open_ts, open=open_p, high=high_p, low=low_p,
                close=close_p, volume=100.0, close_time=close_ts,
                taker_buy_base=50.0,
            ))
        return klines

    @staticmethod
    def create_mock_session_result(
        symbol: str, 
        opinion: str = "BULLISH", 
        current_price: float = 60100.0,
        poc: float = 60000.0,
        vah: float = 61000.0,
        val: float = 59000.0,
        atr: float = 500.0,
        trend_intensity: float = 0.8
    ) -> Dict[str, Any]:
        """Creates a mock output from BinaryStarOrchestrator with customizable topography."""
        return {
            "symbol": symbol,
            "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "final_decision": {
                "opinion": opinion,
                "confidence_score": 85,
                "tactical_parameters": {
                    "current_price": current_price,
                    "entry": current_price - (atr * 0.1),
                    "take_profit": current_price + (atr * 2.0),
                    "stop_loss": current_price - (atr * 1.0),
                    "rr_ratio": 2.1,
                    "projected_holding_hours": 24,
                    "projected_waiting_hours": 4
                },
                "reasoning_chain": "Mocked structural breakout"
            },
            "observation": {
                "symbol": symbol,
                "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "quantitative_metrics": {
                    "price_dynamics": {"current_price": current_price, "atr_macro": atr, "volatility_intensity_index": 1.5},
                    "volume_profile": {"poc": poc, "vah": vah, "val": val, "anchors_above": [], "anchors_below": []},
                    "market_regime": {"volatility_regime": "STABLE", "volume_participation_ratio": 1.0, "trend_intensity": trend_intensity},
                    "sentiment_signals": {"liquidation_clusters": None}
                },
                "visual_context": {}
            }
        }

    @staticmethod
    def create_mock_config() -> Dict[str, Any]:
        """Minimal valid config covering all keys read by the pipeline.

        Visual params come from config/visual_config.yaml at test time.
        Physics constants (projection, warmup, bucket count) are hardcoded.
        """
        return {
            "system": {},
            "network": {
                "gemini": {
                    "api_timeout_seconds": 30,
                    "retry_count": 2,
                    "retry_strategy": {
                        "multiplier": 1,
                        "min_seconds": 2,
                        "max_seconds": 10,
                    },
                    "max_tool_iterations": 5,
                },
            },
            # ── LLM / provider ──────────────────────────────────────
            "llm": {
                "active_provider": "gemini",
                "gemini": {
                    "model": "mock-model",
                    "session_temperature": 0.7,
                    "critic_temperature": 0.2,
                    "evolver_temperature": 0.0,
                    "context_cache": {
                        "enable": True,
                        "expiration_minutes": 60,
                    },
                },
                "binary_star": {
                    "system_instruction": "config/prompts/binary_star.md",
                    "max_rounds": 3,
                    "session_role_prompt": "config/prompts/session.md",
                    "critic_role_prompt": "config/prompts/critic.md",
                    "session_confidence_threshold": 60,
                },
                "evolver": {
                    "role_prompt": "config/prompts/evolver.md",
                },
            },
            # ── Strategy — binary_star / session ────────────────────
            "binary_star": {
                "session": {
                    "min_trade_velocity": 0.5,
                    "stop_loss_buffer_min": 0.1,
                    "temporal_dilation_highway": 1.1,
                    "temporal_dilation_standard": 1.5,
                    "temporal_dilation_climax": 2.0,
                    "temporal_dilation_dead_water": 3.0,
                    "temporal_weight_highway": 2.0,
                    "temporal_weight_standard": 1.0,
                    "temporal_weight_dead_water": 0.5,
                    "temporal_weight_climax": 0.25,
                    "max_holding_hours": 48.0,
                },
            },
            # ── Strategy — analysis / topography / regime ───────────
            "analysis_window": {
                "macro_context": {"time_interval": "1h", "lookback_candles": 100},
                "micro_context": {"time_interval": "15m", "lookback_candles": 100},
                "funding_rate_macro_lookback_candles": 24,
                "cvd_micro_lookback_candles": 4,
                "trend_intensity_macro_lookback_candles": 24,
                "volatility_intensity_macro_lookback_candles": 100,
            },
            "topography_parameters": {
                "volume_profile_value_area_width": 0.7,
                "exponential_moving_average_period": 21,
                "volume_moving_average_period": 21,
                "max_volume_node_count": 3,
                "top_structural_node_count": 3,
                "high_volume_node_detection_threshold": 1.2,
                "low_volume_node_detection_threshold": 0.8,
                "min_node_gap_atr": 1.2,
                "average_true_range_period": 14,
                "bollinger_bands_period": 20,
                "bollinger_bands_std_dev": 2.0,
                "keltner_channels_period": 20,
                "keltner_channels_multiplier": 1.5,
                "wick_skew_lookback_candles": 24,
                "wick_skew_fallback": 0.5,
                "max_liquidation_clusters": 5,
                "max_liquidation_events_to_fetch": 100,
                "default_structural_distance_atr": 2.0,
            },
            "regime_parameters": {
                "trend_intensity_threshold": 0.95,
                "trend_intensity_strong": 0.5,
                "trend_intensity_min_expansion": 0.15,
                "volatility_baseline_ratio": 1.3,
                "volatility_extreme_ratio": 2.0,
                "volume_surge_vs_ma_ratio": 1.5,
                "min_volume_participation_ratio": 1.0,
                "volume_participation_threshold": 1.5,
                "long_short_imbalance_ratio": 1.8,
                "short_heavy_imbalance_ratio": 0.55,
                "poc_gravity_atr_distance": 3.0,
                "ranging_width_atr": 2.0,
                "structural_buffer_atr": 0.05,
                "structural_proximity_threshold": 0.5,
                "vacuum_risk_score": 0.3,
                "wick_skew_exhaustion": 0.6,
                "cvd_intensity_threshold": 0.1,
                "cvd_intensity_extreme": 0.35,
                "funding_extreme_threshold": 0.0005,
                "squeeze_threshold": 1.0,
                "squeeze_audit_threshold": 0.85,
                "breakout_frontrun_atr": 0.45,
                "max_entry_distance_atr": 1.5,
                "chaos_rr_discount": 0.35,
                "min_rr_ranging": 1.0,
                "min_rr_trending": 1.2,
                "liq_radar_long_threshold": 1.05,
                "liq_radar_short_threshold": 0.95,
                "liq_radar_gaussian_sigma": 2.0,
                "liq_radar_grid_bins": 500,
                "liq_radar_grid_padding_atr": 5.0,
            },
            # ── Audit / sandbox / strategy intent ───────────────────
            "audit_review": {
                "forensic_resolution": "1m",
                "atr_period": 14,
                "missed_opportunity_atr_threshold": 2.0,
                "unfilled_proximity_atr_limit": 0.1,
                "catastrophic_miss_atr_threshold": 3.0,
                "mae_threshold_pinpoint": 20.0,
                "mae_threshold_standard": 50.0,
                "mae_threshold_luck": 80.0,
                "base_slippage_bps": 5.0,
                "max_slippage_bps": 50.0,
            },
            "sandbox": {
                "mae_significance_threshold": 15.0,
                "mae_improvement_threshold": 5.0,
            },
            "strategy_intent": "TEST",
        }
    @staticmethod
    def create_mock_ai_response(opinion: str = "BULLISH", confidence: int = 85) -> Dict[str, Any]:
        """Simulates a raw JSON response from the Session or Critic agent."""
        return {
            "opinion": opinion,
            "confidence_score": confidence,
            "tactical_parameters": {
                "current_price": 60100.0,
                "entry": 60000.0,
                "take_profit": 62000.0,
                "stop_loss": 59000.0,
                "projected_holding_hours": 12.0,
                "projected_waiting_hours": 0.5
            },
            "reasoning_chain": "Mocked technical breakout across structural node.",
            "critic_impact": None
        }

    @staticmethod
    def create_mock_critic_response(level: str = "PASS") -> Dict[str, Any]:
        """Simulates an adversarial audit response from the Critic agent."""
        return {
            "veto_level": level,
            "critic_summary": "Structure is sound, but RR is slightly tight." if level == "PASS" else f"{level}: SL is unshielded.",
            "suggested_mitigations": "None" if level == "PASS" else "Move SL behind 59000 POC.",
            "codes": ["SAFE"] if level == "PASS" else ["ANCHOR_VIOLATION"]
        }

    @staticmethod
    def create_mock_math_fact_check(status: str = "VERIFIED", is_valid_rr: bool = True, is_shielded: bool = True) -> Dict[str, Any]:
        """Generates a mock outcome from the math fact check engine."""
        return {
            "status": status,
            "rr_verification": {"rr_ratio": 2.5 if is_valid_rr else 0.8},
            "atr_volatility_verification": {"entry_to_sl_atr": 1.2},
            "structural_armor_verification": {"sl_to_poc_atr": -0.5 if is_shielded else 0.5},
            "holding_time_verification": {"projected_holding_hours": 12.0},
            "compliance_verdict": {
                "rr_is_valid": is_valid_rr,
                "sl_is_shielded": is_shielded,
                "atr_volatility_is_logical": True
            }
        }
