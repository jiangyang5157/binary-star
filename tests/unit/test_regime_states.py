"""Unit tests for regime_states compute functions."""
import pytest
from src.analyzer.regime_states import (
    compute_shared_regime_states,
    compute_session_states,
    compute_critic_states,
    compute_evolver_states,
    _format_states,
)
from src.config.sub_configs import RegimeConfig, RiskConfig, AuditConfig


# ── Shared regime states fixtures ──────────────────────────────

def _make_observation(overrides=None):
    """Minimal valid observation dict for shared macro testing."""
    base = {
        "quantitative_metrics": {
            "price_dynamics": {
                "volatility_expansion_index": 1.0,
                "volatility_intensity_index": 1.0,
            },
            "market_regime": {
                "squeeze_factor": 1.0,
                "trend_intensity": 0.0,
                "volume_participation_ratio": 1.0,
            },
            "sentiment_signals": {
                "cvd_intensity_ratio": 0.0,
                "ls_ratio_micro": 1.0,
                "oi_delta_micro": 0.0,
            },
        }
    }
    if overrides:
        _deep_update(base, overrides)
    return base


def _deep_update(d, updates):
    for k, v in updates.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            _deep_update(d[k], v)
        else:
            d[k] = v


def _make_regime_config(**overrides):
    defaults = {
        "trend_intensity_threshold": 0.3,
        "trend_intensity_strong": 0.6,
        "trend_intensity_min_expansion": 0.2,
        "volatility_baseline_ratio": 1.0,
        "volatility_extreme_ratio": 1.5,
        "volume_surge_vs_ma_ratio": 1.5,
        "long_short_imbalance_ratio": 2.0,
        "short_heavy_imbalance_ratio": 0.5,
        "squeeze_threshold": 0.8,
        "squeeze_audit_threshold": 0.7,
        "ranging_width_atr": 2.0,
        "min_volume_participation_ratio": 1.5,
        "vacuum_risk_score": 0.5,
        "wick_skew_exhaustion": 0.3,
        "cvd_intensity_threshold": 0.3,
        "cvd_intensity_extreme": 0.7,
        "funding_extreme_threshold": 0.01,
        "breakout_frontrun_atr": 0.2,
    }
    defaults.update(overrides)
    return RegimeConfig(**defaults)


# ── Shared 12 macros ─────────────────────────────────────────

class TestSharedRegimeStates:
    def test_is_expanding_true(self):
        obs = _make_observation({"quantitative_metrics": {"price_dynamics": {"volatility_expansion_index": 1.2}}})
        cfg = _make_regime_config(volatility_baseline_ratio=1.0)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_EXPANDING"] is True

    def test_is_expanding_false(self):
        obs = _make_observation({"quantitative_metrics": {"price_dynamics": {"volatility_expansion_index": 0.9}}})
        cfg = _make_regime_config(volatility_baseline_ratio=1.0)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_EXPANDING"] is False

    def test_is_chaos_true(self):
        obs = _make_observation({"quantitative_metrics": {"price_dynamics": {"volatility_expansion_index": 1.8}}})
        cfg = _make_regime_config(volatility_extreme_ratio=1.5)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_CHAOS"] is True

    def test_is_squeezing_true(self):
        obs = _make_observation({"quantitative_metrics": {"market_regime": {"squeeze_factor": 0.5}}})
        cfg = _make_regime_config(squeeze_threshold=0.8)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_SQUEEZING"] is True

    def test_is_trend_true(self):
        obs = _make_observation({"quantitative_metrics": {"market_regime": {"trend_intensity": 0.4}}})
        cfg = _make_regime_config(trend_intensity_threshold=0.3)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_TREND"] is True

    def test_is_trend_strong_true(self):
        obs = _make_observation({"quantitative_metrics": {"market_regime": {"trend_intensity": 0.7}}})
        cfg = _make_regime_config(trend_intensity_strong=0.6)
        result = compute_shared_regime_states(obs, cfg)
        assert result["IS_TREND_STRONG"] is True

    def test_has_volume_surge_true(self):
        obs = _make_observation({"quantitative_metrics": {"market_regime": {"volume_participation_ratio": 2.0}}})
        cfg = _make_regime_config(min_volume_participation_ratio=1.5)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_VOLUME_SURGE"] is True

    def test_has_cvd_momentum_true(self):
        obs = _make_observation({"quantitative_metrics": {"sentiment_signals": {"cvd_intensity_ratio": 0.5}}})
        cfg = _make_regime_config(cvd_intensity_threshold=0.3)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_CVD_MOMENTUM"] is True

    def test_has_bull_flow_true(self):
        obs = _make_observation({"quantitative_metrics": {"sentiment_signals": {"cvd_intensity_ratio": 0.5}}})
        cfg = _make_regime_config(cvd_intensity_threshold=0.3)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_BULL_FLOW"] is True

    def test_has_bear_flow_true(self):
        obs = _make_observation({"quantitative_metrics": {"sentiment_signals": {"cvd_intensity_ratio": -0.5}}})
        cfg = _make_regime_config(cvd_intensity_threshold=0.3)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_BEAR_FLOW"] is True

    def test_has_retail_long_imbalance_true(self):
        obs = _make_observation({"quantitative_metrics": {"sentiment_signals": {"ls_ratio_micro": 3.0}}})
        cfg = _make_regime_config(long_short_imbalance_ratio=2.0)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_RETAIL_LONG_IMBALANCE"] is True

    def test_has_retail_short_imbalance_true(self):
        obs = _make_observation({"quantitative_metrics": {"sentiment_signals": {"ls_ratio_micro": 0.3}}})
        cfg = _make_regime_config(short_heavy_imbalance_ratio=0.5)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_RETAIL_SHORT_IMBALANCE"] is True

    def test_has_absorption_risk_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "sentiment_signals": {
                    "cvd_intensity_ratio": 0.8,
                    "oi_delta_micro": -0.01,
                }
            }
        })
        cfg = _make_regime_config(cvd_intensity_extreme=0.7)
        result = compute_shared_regime_states(obs, cfg)
        assert result["HAS_ABSORPTION_RISK"] is True

    def test_returns_all_12_keys(self):
        obs = _make_observation()
        cfg = _make_regime_config()
        result = compute_shared_regime_states(obs, cfg)
        expected_keys = {
            "IS_EXPANDING", "IS_CHAOS", "IS_SQUEEZING", "IS_TREND",
            "IS_TREND_STRONG", "HAS_VOLUME_SURGE", "HAS_CVD_MOMENTUM",
            "HAS_BULL_FLOW", "HAS_BEAR_FLOW", "HAS_RETAIL_LONG_IMBALANCE",
            "HAS_RETAIL_SHORT_IMBALANCE", "HAS_ABSORPTION_RISK",
        }
        assert set(result.keys()) == expected_keys
        assert all(isinstance(v, bool) for v in result.values())


# ── Session states ───────────────────────────────────────────

class TestSessionStates:
    def test_is_planning_true(self):
        result = compute_session_states(None)
        assert result["IS_PLANNING"] is True
        assert result["IS_SYNTHESIS"] is False

    def test_is_synthesis_true(self):
        result = compute_session_states([{"round": 1}])
        assert result["IS_SYNTHESIS"] is True
        assert result["IS_PLANNING"] is False

    def test_has_terminal_veto_true(self):
        history = [
            {"critic": {"veto_level": "CONSTRUCTIVE"}},
            {"critic": {"veto_level": "TERMINAL"}},
        ]
        result = compute_session_states(history)
        assert result["HAS_TERMINAL_VETO"] is True

    def test_has_terminal_veto_false(self):
        history = [
            {"critic": {"veto_level": "CONSTRUCTIVE"}},
            {"critic": {"veto_level": "PASS"}},
        ]
        result = compute_session_states(history)
        assert result["HAS_TERMINAL_VETO"] is False


# ── Critic states ────────────────────────────────────────────

def _make_last_plan(**overrides):
    base = {
        "opinion": "BULLISH",
        "tactical_parameters": {
            "entry": 90000.0,
            "stop_loss": 89000.0,
            "take_profit": 93000.0,
            "current_price": 90500.0,
            "projected_holding_hours": 4.0,
        },
    }
    base.update(overrides)
    return base


def _make_math_fact_check(**overrides):
    base = {
        "status": "VERIFIED",
        "compliance_verdict": {
            "sl_is_shielded": True,
            "rr_is_valid": True,
            "atr_volatility_is_logical": True,
        },
        "structural_armor_verification": {
            "poc_dist_atr": -0.5,
            "vah_dist_atr": 0.3,
            "val_dist_atr": -1.2,
        },
        "holding_time_verification": {
            "temporal_weight_factor": 1.0,
        },
    }
    base.update(overrides)
    return base


def _make_risk_config(**overrides):
    defaults = {
        "min_rr_ranging": 1.5,
        "min_rr_trending": 1.2,
        "structural_buffer_atr": 0.3,
        "stop_loss_buffer_min": 0.5,
        "poc_gravity_atr_distance": 1.5,
        "max_entry_distance_atr": 1.2,
        "chaos_rr_discount": 0.3,
        "structural_proximity_threshold": 0.5,
        "max_holding_hours": 8.0,
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)


class TestCriticStates:
    def test_is_bullish(self):
        plan = _make_last_plan(opinion="BULLISH")
        result = compute_critic_states(_make_observation(), plan, _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_BULLISH"] is True
        assert result["IS_BEARISH"] is False

    def test_is_entry_safe_bullish_valid(self):
        plan = _make_last_plan(opinion="BULLISH")
        plan["tactical_parameters"]["entry"] = 90000.0
        plan["tactical_parameters"]["current_price"] = 90500.0
        result = compute_critic_states(_make_observation(), plan, _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_ENTRY_SAFE"] is True

    def test_is_entry_safe_bullish_invalid(self):
        plan = _make_last_plan(opinion="BULLISH")
        plan["tactical_parameters"]["entry"] = 91000.0
        plan["tactical_parameters"]["current_price"] = 90500.0
        result = compute_critic_states(_make_observation(), plan, _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_ENTRY_SAFE"] is False

    def test_is_sl_logical_bullish_valid(self):
        plan = _make_last_plan(opinion="BULLISH")
        plan["tactical_parameters"]["entry"] = 90000.0
        plan["tactical_parameters"]["stop_loss"] = 89000.0
        result = compute_critic_states(_make_observation(), plan, _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_SL_LOGICAL"] is True

    def test_is_sl_logical_bearish_valid(self):
        plan = _make_last_plan(opinion="BEARISH")
        plan["tactical_parameters"]["entry"] = 90000.0
        plan["tactical_parameters"]["stop_loss"] = 91000.0
        result = compute_critic_states(_make_observation(), plan, _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_SL_LOGICAL"] is True

    def test_is_sl_shielded_from_math_fact_check(self):
        mfc = _make_math_fact_check()
        mfc["compliance_verdict"]["sl_is_shielded"] = True
        result = compute_critic_states(_make_observation(), _make_last_plan(), mfc,
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_SL_SHIELDED"] is True

    def test_is_rr_valid_from_math_fact_check(self):
        mfc = _make_math_fact_check()
        mfc["compliance_verdict"]["rr_is_valid"] = False
        result = compute_critic_states(_make_observation(), _make_last_plan(), mfc,
                                       _make_regime_config(), _make_risk_config())
        assert result["IS_RR_VALID"] is False

    def test_is_overextending_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "structural_anchors": {"poc_dist_atr": 2.0},
                "market_regime": {"trend_intensity": 0.2},
                "sentiment_signals": {"cvd_intensity_ratio": 0.1},
            }
        })
        plan = _make_last_plan(opinion="BULLISH")
        result = compute_critic_states(obs, plan, _make_math_fact_check(),
                                       _make_regime_config(trend_intensity_strong=0.6),
                                       _make_risk_config(poc_gravity_atr_distance=1.5))
        assert result["IS_OVEREXTENDING"] is True

    def test_has_flow_opposition_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "market_regime": {"trend_intensity": 0.0},
                "sentiment_signals": {"cvd_intensity_ratio": -0.5},
            }
        })
        plan = _make_last_plan(opinion="BULLISH")
        result = compute_critic_states(obs, plan, _make_math_fact_check(),
                                       _make_regime_config(cvd_intensity_threshold=0.3,
                                                           trend_intensity_strong=0.6),
                                       _make_risk_config())
        assert result["HAS_FLOW_OPPOSITION"] is True

    def test_is_volatility_chop_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "price_dynamics": {"volatility_expansion_index": 1.2},
                "market_regime": {"squeeze_factor": 1.0, "trend_intensity": 0.1},
            }
        })
        result = compute_critic_states(obs, _make_last_plan(), _make_math_fact_check(),
                                       _make_regime_config(volatility_baseline_ratio=1.0,
                                                           squeeze_threshold=0.8,
                                                           trend_intensity_min_expansion=0.2),
                                       _make_risk_config())
        assert result["IS_VOLATILITY_CHOP"] is True

    def test_has_liquidity_void_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "volume_profile": {"nearest_lvn_dist_atr": 0.1},
            }
        })
        result = compute_critic_states(obs, _make_last_plan(), _make_math_fact_check(),
                                       _make_regime_config(),
                                       _make_risk_config(structural_buffer_atr=0.3))
        assert result["HAS_LIQUIDITY_VOID"] is True

    def test_is_holding_too_long_true(self):
        plan = _make_last_plan()
        plan["tactical_parameters"]["projected_holding_hours"] = 10.0
        mfc = _make_math_fact_check()
        mfc["holding_time_verification"]["temporal_weight_factor"] = 1.0
        result = compute_critic_states(_make_observation(), plan, mfc,
                                       _make_regime_config(),
                                       _make_risk_config(max_holding_hours=8.0))
        assert result["IS_HOLDING_TOO_LONG"] is True

    def test_has_bear_sentiment_true(self):
        obs = _make_observation({
            "quantitative_metrics": {
                "sentiment_signals": {
                    "ls_ratio_micro": 3.0,
                    "funding_rate": 0.001,
                }
            }
        })
        result = compute_critic_states(obs, _make_last_plan(), _make_math_fact_check(),
                                       _make_regime_config(long_short_imbalance_ratio=2.0,
                                                           funding_extreme_threshold=0.01),
                                       _make_risk_config())
        assert result["HAS_BEAR_SENTIMENT"] is True

    def test_returns_all_16_critic_keys(self):
        result = compute_critic_states(_make_observation(), _make_last_plan(),
                                       _make_math_fact_check(),
                                       _make_regime_config(), _make_risk_config())
        expected = {
            "IS_BULLISH", "IS_BEARISH", "IN_NEUTRAL",
            "HAS_BEAR_SENTIMENT", "HAS_BULL_SENTIMENT",
            "IS_SL_SHIELDED", "IS_RR_VALID",
            "IS_ENTRY_SAFE", "IS_SL_LOGICAL",
            "IS_OVEREXTENDING", "IS_HOLDING_TOO_LONG",
            "HAS_FLOW_OPPOSITION", "IS_VOLATILITY_CHOP",
            "HAS_LIQUIDITY_VOID", "IS_STRUCTURAL_TRAP",
            "HAS_ANCHOR_VIOLATION",
        }
        assert set(result.keys()) == expected


# ── Evolver states ───────────────────────────────────────────

def _make_audit_config(**overrides):
    defaults = {
        "mae_threshold_pinpoint": 0.1,
        "mae_threshold_standard": 0.3,
        "mae_threshold_luck": 0.5,
        "missed_opportunity_atr_threshold": 1.0,
    }
    defaults.update(overrides)
    return AuditConfig(**defaults)


def _make_audit_report(**overrides):
    """Build a minimal audit report matching actual audit JSON structure."""
    base = {
        "session": {
            "final_decision": {
                "opinion": "NEUTRAL",
                "tactical_parameters": {
                    "entry": 90000.0,
                    "take_profit": 93000.0,
                },
            },
            "debate_history": [
                {
                    "critic": {"invalidations": ["[INACTION_BIAS] - ..."]},
                    "math_fact_check": {
                        "compliance_verdict": {
                            "sl_is_shielded": True,
                        },
                    },
                },
            ],
            "observation": {
                "quantitative_metrics": {
                    "price_dynamics": {"atr_macro": 300.0},
                },
            },
        },
        "market_outcome": {
            "tp_sl_result": "TP_HIT",
            "is_filled": True,
            "market_forensics": {
                "max_favorable_runup_atr": 0.3,
            },
            "trade_execution_metrics": {
                "mae_stress_tier": "STANDARD",
                "actual_holding_hours": 5.0,
                "projected_holding_hours": 4.0,
                "temporal_dilation_regime": "temporal_dilation_standard",
            },
        },
        "forensic_verdict": {
            "is_justified_surrender": False,
            "is_catastrophic_miss": False,
        },
    }
    if overrides:
        _deep_update(base, overrides)
    return base


class TestEvolverStates:
    def test_is_batch_significant_true(self):
        reports = [
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
            _make_audit_report(),  # default TP_HIT
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_BATCH_SIGNIFICANT"] is True

    def test_is_batch_significant_false(self):
        reports = [_make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}})]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_BATCH_SIGNIFICANT"] is False

    def test_is_failure_ratio_alarm_true(self):
        reports = [
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
            _make_audit_report(),  # TP_HIT
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_FAILURE_RATIO_ALARM"] is True  # 2/3 > 0.2

    def test_has_systemic_pathology_true(self):
        reports = [
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
            _make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}}),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["HAS_SYSTEMIC_PATHOLOGY"] is True

    def test_is_logic_cowardice_true(self):
        reports = [_make_audit_report()]  # default: NEUTRAL + INACTION_BIAS
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_LOGIC_COWARDICE"] is True

    def test_has_structural_amnesty_true(self):
        reports = [_make_audit_report()]  # default: sl_is_shielded=True, STANDARD
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["HAS_STRUCTURAL_AMNESTY"] is True

    def test_is_profit_evaporation_true(self):
        reports = [
            _make_audit_report(
                **{
                    "market_outcome": {
                        "tp_sl_result": "NEITHER",
                        "market_forensics": {"max_favorable_runup_atr": 0.8},
                    },
                    "session": {
                        "final_decision": {
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 90400.0},
                        },
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_PROFIT_EVAPORATION"] is True  # 0.8 >= 0.6 * 1.33

    def test_is_catastrophic_miss_true(self):
        reports = [
            _make_audit_report(
                **{
                    "market_outcome": {
                        "tp_sl_result": "NEUTRAL",
                        "market_forensics": {"max_favorable_runup_atr": 1.5},
                    },
                    "session": {
                        "final_decision": {
                            "opinion": "NEUTRAL",
                            "tactical_parameters": {"entry": 90000.0, "take_profit": 90400.0},
                        },
                        "observation": {
                            "quantitative_metrics": {
                                "price_dynamics": {"atr_macro": 300.0},
                            },
                        },
                    },
                },
            ),
        ]
        result = compute_evolver_states(reports, _make_audit_config())
        assert result["IS_CATASTROPHIC_MISS"] is True

    def test_returns_all_9_evolver_keys(self):
        reports = [_make_audit_report(**{"market_outcome": {"tp_sl_result": "SL_HIT"}})]
        result = compute_evolver_states(reports, _make_audit_config())
        expected = {
            "IS_BATCH_SIGNIFICANT", "IS_FAILURE_RATIO_ALARM",
            "HAS_SYSTEMIC_PATHOLOGY", "IS_LOGIC_COWARDICE",
            "HAS_STRUCTURAL_AMNESTY", "IS_PROFIT_EVAPORATION",
            "IS_CATASTROPHIC_MISS", "REQUIRES_TIME_RECALIBRATION",
            "time_calibration_report",
        }
        assert set(result.keys()) == expected


# ── Format utility ───────────────────────────────────────────

class TestFormatStates:
    def test_format_states_json(self):
        states = {"IS_EXPANDING": True, "IS_CHAOS": False}
        result = _format_states(states)
        assert '"IS_EXPANDING": true' in result
        assert '"IS_CHAOS": false' in result

    def test_format_states_is_valid_json(self):
        import json
        states = {"IS_EXPANDING": True, "HAS_CVD_MOMENTUM": False}
        parsed = json.loads(_format_states(states))
        assert parsed == states
