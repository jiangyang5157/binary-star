"""Config loaders that build sub-configs from YAML dicts."""
from typing import Any

from src.config.sub_configs import (
    AuditConfig,
    RegimeConfig,
    RiskConfig,
    TemporalConfig,
    VisualConfig,
)


def _f(d: dict, key: str) -> float:
    return float(d[key])


def _i(d: dict, key: str) -> int:
    return int(d[key])


def _s(d: dict, key: str) -> str:
    return str(d[key])


def load_regime_config(cfg: dict[str, Any]) -> RegimeConfig:
    r = cfg["regime_parameters"]
    return RegimeConfig(
        trend_intensity_threshold=_f(r, "trend_intensity_threshold"),
        trend_intensity_strong=_f(r, "trend_intensity_strong"),
        trend_intensity_min_expansion=_f(r, "trend_intensity_min_expansion"),
        volatility_baseline_ratio=_f(r, "volatility_baseline_ratio"),
        volatility_extreme_ratio=_f(r, "volatility_extreme_ratio"),
        volume_surge_vs_ma_ratio=_f(r, "volume_surge_vs_ma_ratio"),
        long_short_imbalance_ratio=_f(r, "long_short_imbalance_ratio"),
        short_heavy_imbalance_ratio=_f(r, "short_heavy_imbalance_ratio"),
        squeeze_threshold=_f(r, "squeeze_threshold"),
        squeeze_audit_threshold=_f(r, "squeeze_audit_threshold"),
        ranging_width_atr=_f(r, "ranging_width_atr"),
        min_volume_participation_ratio=_f(r, "min_volume_participation_ratio"),
        vacuum_risk_score=_f(r, "vacuum_risk_score"),
        wick_skew_exhaustion=_f(r, "wick_skew_exhaustion"),
        cvd_intensity_threshold=_f(r, "cvd_intensity_threshold"),
        cvd_intensity_extreme=_f(r, "cvd_intensity_extreme"),
        funding_extreme_threshold=_f(r, "funding_extreme_threshold"),
        breakout_frontrun_atr=_f(r, "breakout_frontrun_atr"),
    )


def load_temporal_config(cfg: dict[str, Any]) -> TemporalConfig:
    s = cfg["binary_star"]["session"]
    return TemporalConfig(
        min_trade_velocity=_f(s, "min_trade_velocity"),
        temporal_dilation_dead_water=_f(s, "temporal_dilation_dead_water"),
        temporal_dilation_highway=_f(s, "temporal_dilation_highway"),
        temporal_dilation_climax=_f(s, "temporal_dilation_climax"),
        temporal_dilation_standard=_f(s, "temporal_dilation_standard"),
        temporal_weight_dead_water=_f(s, "temporal_weight_dead_water"),
        temporal_weight_highway=_f(s, "temporal_weight_highway"),
        temporal_weight_climax=_f(s, "temporal_weight_climax"),
        temporal_weight_standard=_f(s, "temporal_weight_standard"),
    )


def load_risk_config(cfg: dict[str, Any]) -> RiskConfig:
    r = cfg["regime_parameters"]
    s = cfg["binary_star"]["session"]
    return RiskConfig(
        min_rr_ranging=_f(r, "min_rr_ranging"),
        min_rr_trending=_f(r, "min_rr_trending"),
        structural_buffer_atr=_f(r, "structural_buffer_atr"),
        stop_loss_buffer_min=_f(s, "stop_loss_buffer_min"),
        poc_gravity_atr_distance=_f(r, "poc_gravity_atr_distance"),
        max_entry_distance_atr=_f(r, "max_entry_distance_atr"),
        chaos_rr_discount=_f(r, "chaos_rr_discount"),
        structural_proximity_threshold=_f(r, "structural_proximity_threshold"),
        max_holding_hours=_f(s, "max_holding_hours"),
    )


def load_audit_config(cfg: dict[str, Any]) -> AuditConfig:
    a = cfg["audit_review"]
    return AuditConfig(
        mae_threshold_pinpoint=_f(a, "mae_threshold_pinpoint"),
        mae_threshold_standard=_f(a, "mae_threshold_standard"),
        mae_threshold_luck=_f(a, "mae_threshold_luck"),
        missed_opportunity_atr_threshold=_f(a, "missed_opportunity_atr_threshold"),
    )


def load_visual_config(cfg: dict[str, Any]) -> VisualConfig:
    v = cfg["visuals"]
    t = cfg["topography_parameters"]
    return VisualConfig(
        volume_profile_width_ratio=_f(v["volume_profile"], "width_ratio"),
        volume_profile_value_area_width=_f(t, "volume_profile_value_area_width"),
        render_dpi=_i(v, "render_dpi"),
        up_color=_s(v, "up_color"),
        down_color=_s(v, "down_color"),
        bg_color=_s(v, "bg_color"),
        poc_color=_s(v, "poc_color"),
        vah_val_color=_s(v, "vah_val_color"),
        current_price_color=_s(v, "current_price_color"),
    )
