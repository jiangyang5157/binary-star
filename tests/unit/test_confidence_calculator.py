"""Unit tests for confidence_calculator."""
import pytest
from src.analyzer.confidence_calculator import (
    compute_confidence,
    _score_anchor_quality,
    _score_betweenness,
    _score_entry_proximity,
    _score_entry_vacuum,
    _score_multi_anchor,
    _score_flow_alignment,
    _score_regime_fit,
    _score_tp_proportional,
    _score_polarity,
    _score_holding_ratio,
    _score_wait_hold,
    _score_squeeze_comp,
    _score_sentiment_risk,
    _calc_debate_penalty,
    _infer_strategy,
)
from src.config.sub_configs import RegimeConfig, RiskConfig


# ── Fixtures (load base from live YAML — test overrides stay explicit) ──

from src.utils.pipeline_utils import load_combined_config as _load_cfg
from src.config.loader import load_regime_config as _load_rg, load_risk_config as _load_rk
from dataclasses import asdict as _asdict
_BASE_CFG = _load_cfg()


def _make_regime_config(**overrides):
    base = _asdict(_load_rg(_BASE_CFG))
    base.update(overrides)
    return RegimeConfig(**base)


def _make_risk_config(**overrides):
    base = _asdict(_load_rk(_BASE_CFG))
    base.update(overrides)
    return RiskConfig(**base)


def _make_plan(**overrides):
    base = {
        "opinion": "BULLISH",
        "tactical_parameters": {
            "entry": 90000.0, "stop_loss": 89000.0, "take_profit": 93000.0,
            "current_price": 90500.0,
            "projected_holding_hours": 4.0, "projected_waiting_hours": 0.8,
        },
    }
    base.update(overrides)
    return base


def _make_observation(**overrides):
    base = {
        "quantitative_metrics": {
            "price_dynamics": {
                "atr_macro": 1000.0, "volatility_expansion_index": 1.0,
            },
            "market_regime": {
                "trend_intensity": 0.5, "squeeze_factor": 1.0,
                "volume_participation_ratio": 1.0,
                "temporal_physics": {
                    "unit_atr_holding_hours": 4.0,
                },
            },
            "sentiment_signals": {
                "cvd_intensity_ratio": 0.4, "ls_ratio_micro": 1.0,
                "funding_rate": 0.001, "liquidation_clusters": {},
            },
            "volume_profile": {
                "anchors_above": [],
                "anchors_below": [
                    {"price": 88500.0, "type": "HVN", "strength": 0.9},
                    {"price": 88000.0, "type": "HVN", "strength": 0.6},
                ],
            },
            "structural_anchors": {"poc_dist_atr": 0.5},
        },
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


def _make_math_fact_check(**overrides):
    base = {
        "compliance_verdict": {
            "sl_is_shielded": True, "rr_is_valid": True,
            "atr_volatility_is_logical": True,
        },
        "structural_armor_verification": {
            "poc_dist_atr": -0.5, "vah_dist_atr": 0.3, "val_dist_atr": -1.2,
        },
        "holding_time_verification": {
            "temporal_weight_factor": 1.0,
        },
    }
    base.update(overrides)
    return base


# ── Entry Point Tests ────────────────────────────────────────

class TestComputeConfidence:
    def test_neutral_returns_zero(self):
        plan = _make_plan(opinion="NEUTRAL")
        result = compute_confidence(plan, _make_observation(),
                                    _make_math_fact_check(), None,
                                    _make_regime_config(), _make_risk_config())
        assert result == 0.0

    def test_rr_invalid_returns_zero(self):
        mfc = _make_math_fact_check()
        mfc["compliance_verdict"]["rr_is_valid"] = False
        result = compute_confidence(_make_plan(), _make_observation(),
                                    mfc, None,
                                    _make_regime_config(), _make_risk_config())
        assert result == 0.0

    def test_zero_atr_returns_zero(self):
        obs = _make_observation(quantitative_metrics={"price_dynamics": {"atr_macro": 0.0}})
        result = compute_confidence(_make_plan(), obs,
                                    _make_math_fact_check(), None,
                                    _make_regime_config(), _make_risk_config())
        assert result == 0.0

    def test_healthy_bullish_plan_scores_positive(self):
        result = compute_confidence(_make_plan(), _make_observation(),
                                    _make_math_fact_check(), None,
                                    _make_regime_config(), _make_risk_config())
        assert result > 0
        assert result <= 100

    def test_clamped_to_100(self):
        # A plan with perfect everything should not exceed 100
        result = compute_confidence(_make_plan(), _make_observation(),
                                    _make_math_fact_check(), None,
                                    _make_regime_config(), _make_risk_config())
        assert result <= 100


# ── D1 Tests ─────────────────────────────────────────────────

class TestAnchorQuality:
    def test_strong_hvn_anchor(self):
        nodes = [{"price": 88500.0, "type": "HVN", "strength": 0.9}]
        result = _score_anchor_quality(90000.0, 89000.0, True, nodes,
                                       1000.0, {})
        assert result >= 12

    def test_no_anchor_returns_zero(self):
        result = _score_anchor_quality(90000.0, 89000.0, True, [],
                                       1000.0, {})
        assert result == 0

    def test_lvn_anchor_scores_lower(self):
        nodes = [{"price": 88500.0, "type": "LVN", "strength": 0.3, "vacuum_score": 0.7}]
        result = _score_anchor_quality(90000.0, 89000.0, True, nodes,
                                       1000.0, {})
        assert 3 <= result <= 7


class TestBetweenness:
    def test_perfect_betweenness(self):
        nodes = [{"price": 88500.0, "type": "HVN", "strength": 0.9}]
        result = _score_betweenness(90000.0, 89000.0, True, nodes, 1000.0, False)
        assert result == 10  # gap entry-anchor=1.5ATR, anchor-sl=0.5ATR, both >= 0.3

    def test_no_anchor(self):
        result = _score_betweenness(90000.0, 89000.0, True, [], 1000.0, False)
        assert result == 0

    def test_dks_substitution(self):
        result = _score_betweenness(90000.0, 89000.0, True, [], 1000.0, True)
        assert 3 <= result <= 5  # DKS when trend_strong + no anchor


class TestEntryProximity:
    def test_tight_entry(self):
        result = _score_entry_proximity(90500.0, 90600.0, 1000.0, _make_risk_config())
        assert result == 5  # 0.1 ATR

    def test_exceeds_max(self):
        result = _score_entry_proximity(90000.0, 92000.0, 1000.0, _make_risk_config())
        assert result == 0  # 2.0 ATR > 1.2 max


class TestEntryVacuum:
    def test_on_hvn(self):
        nodes = [{"price": 90000.0, "type": "HVN", "strength": 0.8}]
        result = _score_entry_vacuum(90000.0, nodes, 1000.0)
        assert result == 5

    def test_pure_vacuum(self):
        result = _score_entry_vacuum(90000.0, [], 1000.0)
        assert result == 0


class TestMultiAnchor:
    def test_second_anchor_exists(self):
        nodes = [
            {"price": 88500.0, "type": "HVN", "strength": 0.9},
            {"price": 88000.0, "type": "HVN", "strength": 0.6},
        ]
        result = _score_multi_anchor(90000.0, 89000.0, True, nodes, 1000.0)
        assert result >= 2

    def test_no_second_anchor(self):
        nodes = [{"price": 88500.0, "type": "HVN", "strength": 0.9}]
        result = _score_multi_anchor(90000.0, 89000.0, True, nodes, 1000.0)
        assert result == 0


# ── D2 Tests ─────────────────────────────────────────────────

class TestFlowAlignment:
    def test_both_strong_aligned_bullish(self):
        result = _score_flow_alignment("BULLISH", True, True, 0.7, 0.5)
        assert result == 10

    def test_contradiction(self):
        result = _score_flow_alignment("BULLISH", True, True, -0.7, -0.5)
        assert result == 0

    def test_neutral(self):
        result = _score_flow_alignment("BULLISH", False, False, 0.1, 0.1)
        assert 2 <= result <= 4


class TestRegimeFit:
    def test_momentum_surge_canonical(self):
        result = _score_regime_fit("momentum_surge", True, True, False, False,
                                   0.5, _make_risk_config())
        assert result == 10

    def test_momentum_in_ranging_mismatch(self):
        result = _score_regime_fit("momentum_surge", False, False, False, False,
                                   0.5, _make_risk_config())
        assert 0 <= result <= 3

    def test_gravity_cap(self):
        result = _score_regime_fit("dle_mean_reversion", False, False, False, False,
                                   2.0, _make_risk_config(poc_gravity_atr_distance=1.5))
        assert result <= 5  # gravity cap applied


class TestTpProportional:
    def test_chaos_tight_tp(self):
        result = _score_tp_proportional(91000.0, 90000.0, True, True, False,
                                        {"vah": 91500.0}, 1000.0)
        assert result == 5  # tp within first boundary (VAH at 91500)

    def test_normal_proportional(self):
        result = _score_tp_proportional(93000.0, 90000.0, True, False, False,
                                        {}, 1000.0)
        assert 3 <= result <= 4  # 3 ATR distance


class TestPolarity:
    def test_all_consistent(self):
        result = _score_polarity("BULLISH", 0.7, 0.5, "momentum_surge")
        assert result == 5

    def test_major_contradiction(self):
        # BULLISH trade with bearish trend + bearish CVD = 1/3 consistency
        # (neutral dle strategy is compatible, but trend/CVD both oppose)
        result = _score_polarity("BULLISH", -0.7, -0.5, "dle_mean_reversion")
        assert result == 1.0


# ── D3 Tests ─────────────────────────────────────────────────

class TestHoldingRatio:
    def test_ideal_ratio(self):
        # entry=90000, tp=93000 → 3 ATR distance. proj_holding=12h.
        # unit_atr_holding_hours=4 → expected=3*4=12. ratio=12/12=1.0
        result = _score_holding_ratio(12.0, 90000.0, 93000.0, 1000.0,
                                      {"unit_atr_holding_hours": 4.0})
        assert 8 <= result <= 10

    def test_too_long(self):
        result = _score_holding_ratio(300.0, 90000.0, 93000.0, 1000.0,
                                      {"unit_atr_holding_hours": 4.0})
        assert 1 <= result <= 3  # ratio=300/120=2.5 > 2.0

    def test_missing_temporal_physics(self):
        result = _score_holding_ratio(120.0, 90000.0, 93000.0, 1000.0, None)
        assert result == 0


class TestWaitHold:
    def test_tight_wait(self):
        result = _score_wait_hold(0.5, 4.0)
        assert result == 8  # 0.125

    def test_long_wait(self):
        result = _score_wait_hold(3.0, 4.0)
        assert 0 <= result <= 1  # 0.75 > 0.50


class TestSqueezeComp:
    def test_not_chaos_not_squeeze_ignored(self):
        result = _score_squeeze_comp(False, False, 93000.0, 90000.0, True, {}, 1000.0)
        assert result == 0

    def test_chaos_tight_compression(self):
        result = _score_squeeze_comp(True, False, 91000.0, 90000.0, True,
                                     {"vah": 91500.0}, 1000.0)
        assert result == 5


class TestSentimentRisk:
    def test_balanced(self):
        result = _score_sentiment_risk("BULLISH",
                                       {"ls_ratio_micro": 1.0, "funding_rate": 0.001},
                                       _make_regime_config(
                                           long_short_imbalance_ratio=1.5,
                                           funding_extreme_threshold=0.01), None)
        assert result == 7

    def test_retail_extreme_against(self):
        result = _score_sentiment_risk("BULLISH",
                                       {"ls_ratio_micro": 3.0, "funding_rate": 0.001},
                                       _make_regime_config(), None)
        assert 0 <= result <= 2

    def test_squeeze_hardening(self):
        history = [{"critic": {"invalidations": ["[RETAIL_LONG_SQUEEZE] - ..."]}}]
        result = _score_sentiment_risk("BULLISH",
                                       {"ls_ratio_micro": 3.0, "funding_rate": 0.001},
                                       _make_regime_config(), history)
        assert result == 7  # SQUEEZE HARDENING override


# ── Penalty Tests ────────────────────────────────────────────

class TestDebatePenalty:
    def test_planning_zero_penalty(self):
        result = _calc_debate_penalty(None, 90000.0, 1000.0)
        assert result == 0

    def test_terminal_paradigm_shift(self):
        history = [{"plan": {"tactical_parameters": {"entry": 85000.0}},
                    "critic": {"veto_level": "TERMINAL"}}]
        # Current plan entry is 90000 — 5000 diff > 1000 ATR → paradigm
        penalty = _calc_debate_penalty(history, 90000.0, 1000.0)
        assert penalty >= 10  # abs(90000-85000)=5000 > 1000 ATR → paradigm

    def test_pass_round1_zero_penalty(self):
        history = [{"critic": {"veto_level": "PASS"}}]
        result = _calc_debate_penalty(history, 90000.0, 1000.0)
        assert result == 0


# ── Strategy Inference Tests ─────────────────────────────────

class TestInferStrategy:
    def test_chaos_returns_hit_and_run(self):
        result = _infer_strategy(90000.0, 90500.0, 1000.0, True, True, True,
                                 True, "BULLISH", 0.7, [], {})
        assert result == "hit_and_run"

    def test_momentum_surge(self):
        result = _infer_strategy(90400.0, 90500.0, 1000.0, True, True, False,
                                 False, "BULLISH", 0.7, [], {})
        assert result == "momentum_surge"

    def test_default_dle(self):
        result = _infer_strategy(89000.0, 90500.0, 1000.0, False, False, False,
                                 False, "BULLISH", 0.1, [], {})
        assert result == "dle_mean_reversion"
