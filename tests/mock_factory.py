import datetime
import random
from typing import List, Dict, Any

class MockDataFactory:
    """Universal generator for deterministic test data."""

    @staticmethod
    def create_mock_klines(symbol: str, count: int = 100, trend: str = "bullish") -> List[List[Any]]:
        """
        Generates simulated Binance klines.
        Structure: [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...]
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
            klines.append([open_ts, open_p, high_p, low_p, close_p, 100.0, close_ts])
        
        return klines

    @staticmethod
    def create_mock_session_result(symbol: str, opinion: str = "BULLISH") -> Dict[str, Any]:
        """Creates a mock output from BinaryStarOrchestrator."""
        return {
            "symbol": symbol,
            "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "final_decision": {
                "opinion": opinion,
                "confidence_score": 85,
                "tactical_parameters": {
                    "current_price": 60100,
                    "entry": 60000,
                    "take_profit": 62000,
                    "stop_loss": 59000,
                    "rr_ratio": 2.0,
                    "holding_time_hours": 24
                },
                "reasoning_chain": "Mocked structural breakout"
            },
            "observation": {
                "symbol": symbol,
                "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "quantitative_metrics": {
                    "price_dynamics": {"current_price": 60100, "atr_macro": 500, "volatility_intensity_index": 1.0},
                    "volume_profile": {"poc": 60000, "vah": 61000, "val": 59000, "anchors_above": [], "anchors_below": []},
                    "market_regime": {"volatility_regime": "STABLE", "vol_participation_ratio": 1.0},
                    "sentiment_signals": {"liquidation_clusters": []}
                }
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
                    "max_tool_iterations": 5
                }
            },
            "system": {
                "default_symbol": "BTCUSDT",
                "notification_confidence_floor": 50
            },
            "visuals": {
                "up_color": "#26a69a",
                "down_color": "#ef5350",
                "bg_color": "#131722",
                "grid_color": "#333333",
                "poc_color": "#ff9800",
                "value_area_color": "#fbc02d",
                "liq_buy_color": "#00ff88",
                "liq_sell_color": "#ff3366",
                "vol_profile_width_ratio": 0.20,
                "vol_profile_smoothing_sigma": 2.0,
                "vol_profile_color": "#64b5f6",
                "vol_profile_alpha": 0.4,
                "chart_main_panel_weight": 4,
                "chart_volume_panel_weight": 1,
                "render_dpi": 180
            },
            "backtest": {
                "indicator_warmup_multiplier": 5.0,
                "default_samples": 1
            },
            # 2. Strategy Config Keys
            "binary_star": {
                "model": "mock-model",
                "max_rounds": 3,
                "skepticism_halt_limit": 20,
                "cache_expiration_minutes": 10,
                "system_instruction": "config/strategy_config.yaml",
                "session": {
                    "model_temperature": 0.7,
                    "role_definition_prompt": "prompts/session.md",
                    "min_trade_velocity": 0.5,
                    "stop_loss_buffer_min": 0.1,
                    "stop_loss_buffer_max": 0.5,
                    "score_confidence_base": 80.0,
                    "score_confidence_decay_min": 2.0,
                    "score_confidence_decay_max": 10.0,
                    "holding_time_modifier": 1.0,
                    "holding_friction_highway": 1.1,
                    "holding_friction_standard": 1.5,
                    "holding_friction_climax": 2.0,
                    "holding_friction_dead_water": 3.0
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
                "funding_rate_lookback_hours": 24.0,
                "order_flow_lookback_hours": 24.0,
                "trend_intensity_lookback_hours": 24.0,
                "volatility_intensity_lookback_hours": 100
            },
            "topography_parameters": {
                "volume_profile_value_area_width": 0.7,
                "volume_profile_price_bucket_count": 24,
                "exponential_moving_average_period": 21,
                "volume_moving_average_period": 21,
                "max_high_volume_node_count": 3,
                "max_low_volume_node_count": 3,
                "high_volume_node_detection_threshold": 1.2,
                "low_volume_node_detection_threshold": 0.8,
                "min_price_gap_between_nodes": 10,
                "top_structural_node_count": 3,
                "average_true_range_period": 14,
                "bollinger_bands_period": 20,
                "bollinger_bands_std_dev": 2.0,
                "keltner_channels_period": 20,
                "keltner_channels_multiplier": 1.5,
                "wick_skewness_period": 24,
                "wick_skew_fallback": 0.5,
                "max_liquidation_clusters": 5,
                "max_liquidation_events_to_fetch": 100,
                "max_liquidation_events_for_context": 50,
                "liquidation_cluster_atr_multiplier": 0.25,
                "liquidation_cluster_fallback_percentage": 0.005,
                "default_structural_distance_atr": 2.0
            },
            "regime_parameters": {
                "trend_intensity_threshold": 0.3,
                "volatility_baseline_ratio": 1.0,
                "volatility_expansion_ratio": 1.5,
                "volatility_extreme_ratio": 3.0,
                "vol_surge_vs_ma_ratio": 2.0,
                "long_short_imbalance_ratio": 1.5,
                "poc_gravity_atr_distance": 1.0,
                "vacuum_risk_score": 3.0,
                "wick_skewness_exhaustion": 0.6,
                "wick_skewness_momentum_bullish": 0.6,
                "wick_skewness_momentum_bearish": 0.4,
                "trend_intensity_strong": 0.8,
                "min_rr_ranging": 1.5,
                "min_rr_trending": 2.5,
                "min_vol_participation_ratio": 1.0,
                "squeeze_threshold": 0.1,
                "squeeze_audit_threshold": 0.2,
                "ranging_width_atr": 1.5,
                "cvd_slope_threshold": 0.1,
                "cvd_intensity_threshold": 0.05,
                "cvd_intensity_extreme": 0.15,
                "funding_extreme_threshold": 0.01,
                "structural_proximity_threshold": 1.0,
                "breakout_buffer_atr": 0.2,
                "breakout_frontrun_atr": 0.1,
                "poc_magnet_atr_threshold": 0.5,
                "gravity_volume_override_ratio": 1.5,
                "noise_filter_atr_floor": 0.3,
                "vol_participation_threshold": 2.0,
                "linear_reg_slope_lookback": 24,
                "anchor_drift_threshold": 1.0,
                "poc_confluence_strength": 0.9,
                "structural_buffer_atr": 0.05
            },
            "sandbox": {
                "acceptance_rate_threshold": 0.5,
                "mae_significance_threshold": 15.0,
                "mae_improvement_threshold": 5.0
            },
            "audit_review": {
                "forensic_resolution": "1m",
                "mae_stress_tolerance": 0.5,
                "atr_period": 14,
                "missed_opportunity_atr_threshold": 2.0,
                "unfilled_proximity_atr_limit": 0.1,
                "catastrophic_miss_pct_threshold": 3.0,
                "mae_stress_thresholds": {
                    "pinpoint": 15.0,
                    "standard": 50.0,
                    "luck": 80.0
                },
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
                "holding_time_hours": 12.0
            },
            "reasoning_chain": "Mocked technical breakout across structural node.",
            "critic_impact": None
        }

    @staticmethod
    def create_mock_critic_response(score: int = 15, veto: bool = False) -> Dict[str, Any]:
        """Simulates an adversarial audit response from the Critic agent."""
        return {
            "skepticism_score": score,
            "veto_triggered": veto,
            "critic_summary": "Structure is sound, but RR is slightly tight." if not veto else "TERMINAL: SL is unshielded.",
            "suggested_mitigations": "None" if not veto else "Move SL behind 59000 POC.",
            "codes": ["SAFE"] if not veto else ["ANCHOR_VIOLATION"]
        }
