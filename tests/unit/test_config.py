"""Test that sub-config loaders produce correct values from actual YAML."""
import pytest
from src.utils.pipeline_utils import load_combined_config
from src.config.loader import (
    load_regime_config, load_temporal_config, load_risk_config,
    load_audit_config, load_visual_config,
)
from src.config.sub_configs import (
    RegimeConfig, TemporalConfig, RiskConfig, AuditConfig, VisualConfig,
)


@pytest.fixture(scope="module")
def cfg():
    """Load the combined (global + strategy) config once per module."""
    return load_combined_config()


def test_regime_config_loads_from_yaml(cfg):
    r = load_regime_config(cfg)
    assert isinstance(r, RegimeConfig)
    assert r.trend_intensity_threshold == 0.2
    assert r.volatility_extreme_ratio == 2.2
    assert isinstance(r.squeeze_threshold, float)
    assert r.trend_intensity_strong > 0
    assert r.volatility_baseline_ratio > 0
    assert r.breakout_frontrun_atr > 0


def test_temporal_config_loads_from_yaml(cfg):
    t = load_temporal_config(cfg)
    assert isinstance(t, TemporalConfig)
    assert isinstance(t.min_trade_velocity, float)
    assert t.temporal_dilation_standard > 0
    assert t.temporal_weight_highway > 0
    assert t.temporal_weight_dead_water > 0


def test_risk_config_loads_from_yaml(cfg):
    k = load_risk_config(cfg)
    assert isinstance(k, RiskConfig)
    assert k.min_rr_trending > 0
    assert k.structural_buffer_atr > 0
    assert k.min_rr_ranging > 0
    assert k.max_holding_hours > 0


def test_audit_config_loads_from_yaml(cfg):
    a = load_audit_config(cfg)
    assert isinstance(a, AuditConfig)
    assert a.mae_threshold_pinpoint > 0
    assert a.mae_threshold_standard > 0
    assert a.mae_threshold_luck > 0
    assert a.mae_threshold_pinpoint < a.mae_threshold_standard < a.mae_threshold_luck


def test_visual_config_loads_from_yaml(cfg):
    v = load_visual_config(cfg)
    assert isinstance(v, VisualConfig)
    assert isinstance(v.render_dpi, int)
    assert v.render_dpi > 0
    assert v.up_color.startswith("#")
    assert v.down_color.startswith("#")
