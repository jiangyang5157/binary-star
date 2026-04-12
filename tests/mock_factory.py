import datetime
import random
from typing import List, Dict, Any
from src.infrastructure.exchange.models import KlineData

class MockDataFactory:
    """Universal generator for deterministic test data."""

    @staticmethod
    def create_mock_klines(symbol: str, count: int = 100, trend: str = "bullish") -> List[KlineData]:
        """
        Generates simulated Binance klines as Domain objects.
        """
        base_price = 60000.0
        klines = []
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        interval_ms = 60000 * 15 # 15m

        for i in range(count):
            open_ts = now_ts - (count - i) * interval_ms
            close_ts = open_ts + interval_ms - 1
            
            # Simulated price movement
            drift = 50.0 if trend == "bullish" else -50.0
            noise = random.uniform(-20, 20)
            
            open_p = base_price + (i * drift) + noise
            close_p = open_p + drift + random.uniform(-10, 10)
            high_p = max(open_p, close_p) + random.uniform(5, 15)
            low_p = min(open_p, close_p) - random.uniform(5, 15)
            
            # [OpenTime, Open, High, Low, Close, Volume, CloseTime]
            # Since we now map everything safely, other missing fields are automatically None
            klines.append(KlineData(
                open_time=open_ts,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=100.0,
                close_time=close_ts,
                taker_buy_base=50.0  # Optional fallback value for simulation
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
        """Generates a minimal valid configuration that satisfies both strategy and global config requirements."""
        return {
            # 1. Global Config Keys (from global_config.yaml)
            "network": {
                "gemini": {
                    "api_timeout_seconds": 30,
                    "retry_count": 2,
                    "retry_strategy": {
                        "multiplier": 1,
                        "min_seconds": 2,
                        "max_seconds": 10
                    },
                    "max_tool_iterations": 5,
                    "context_cache": {
                        "enable": True,
                        "expiration_minutes": 60
                    }
                }
            },
            "system": {
                "default_symbol": "BTCUSDT",
                "notification_confidence_floor": 50
            },
            "visuals": {
                "up_color": "#089981",
                "down_color": "#F23645",
                "bg_color": "#131722",
                "poc_color": "#FF9800",
                "vah_val_color": "#2196F3",
                "current_price_color": "#ffffff",
                "liq_radar_atr_multiplier": 0.5,
                "volume_profile": {
                    "width_ratio": 0.2,
                    "smoothing_sigma": 1.0,
                    "color": "#787b86",
                    "alpha": 0.4
                },
                "chart_main_panel_weight": 4,
                "chart_volume_panel_weight": 1,
                "render_dpi": 100,
                "chart_trendline": {
                    "peak_count": 5,
                    "window": 10
                },
                "liq_max_alpha": 0.3,
                "liq_min_alpha": 0.1,
                "liq_legacy_alpha_factor": 5.0,
                "liq_legacy_min_alpha": 0.1,
                "liq_legacy_max_alpha": 0.5,
                "default_structural_distance_atr": 2.0
            },
            "analytical": {
                "indicator_warmup_multiplier": 5.0,
            },
            "backtest": {
                "default_samples": 1
            },
            # 2. Strategy Config Keys
            "binary_star": {
                "model": "mock-model",
                "max_rounds": 3,
                "cache_expiration_minutes": 10,
                "system_instruction": "config/strategy_config.yaml",
                "session": {
                    "model_temperature": 0.7,
                    "role_definition_prompt": "prompts/session.md",
                    "min_trade_velocity": 0.5,
                    "stop_loss_buffer_min": 0.1,
                    "score_confidence_base": 80.0,
                    "score_confidence_decay_min": 5.0,
                    "score_confidence_decay_max": 20.0,
                    "score_confidence_bonus": 10.0,
                    "holding_time_modifier": 1.0,
                    "temporal_dilation_highway": 1.1,
                    "temporal_dilation_standard": 1.5,
                    "temporal_dilation_climax": 2.0,
                    "temporal_dilation_dead_water": 3.0
                },
                "critic": {
                    "model_temperature": 0.2,
                    "role_definition_prompt": "src/agent/prompts/critic.md",
                    "threshold_skepticism_clear": 20,
                    "threshold_skepticism_weak": 40,
                    "threshold_skepticism_constructive": 60
                }
            },
            "agent_model_shared_config": {"max_tool_iterations": 5},
            "analysis_window": {
                "macro_context": {"time_interval": "1h", "lookback_candles": 100},
                "micro_context": {"time_interval": "15m", "lookback_candles": 100},
                "funding_rate_macro_lookback_candles": 24,
                "cvd_micro_lookback_candles": 4,
                "trend_intensity_macro_lookback_candles": 24,
                "volatility_intensity_macro_lookback_candles": 100
            },
            "topography_parameters": {
                "volume_profile_value_area_width": 0.7,
                "volume_profile_price_bucket_count": 24,
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
                "liquidation_cluster_atr_multiplier": 0.25,
                "liquidation_cluster_fallback_percentage": 0.005,
                "default_structural_distance_atr": 2.0
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
                "liq_radar_projection_50x": 0.02,
                "liq_radar_projection_25x": 0.04,
                "liq_radar_weight_25x": 0.6,
                "liq_radar_gaussian_sigma": 2.0,
                "liq_radar_grid_bins": 500,
                "liq_radar_grid_padding_atr": 5.0
            },
            "sandbox": {
                "mae_significance_threshold": 15.0,
                "mae_improvement_threshold": 5.0
            },
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
                "max_slippage_bps": 50.0
            },
            "strategy_intent": "TEST"
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
    def create_mock_critic_response(score: int = 15, level: str = "PASS") -> Dict[str, Any]:
        """Simulates an adversarial audit response from the Critic agent."""
        return {
            "skepticism_score": score,
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
