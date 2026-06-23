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
    """Type-safe float extractor. Raises KeyError if key is missing."""
    return float(d[key])


def _i(d: dict, key: str) -> int:
    """Type-safe int extractor. Raises KeyError if key is missing."""
    return int(d[key])


def _s(d: dict, key: str) -> str:
    """Type-safe str extractor. Raises KeyError if key is missing."""
    return str(d[key])


def load_regime_config(cfg: dict[str, Any]) -> RegimeConfig:
    r = cfg["regime_parameters"]
    return RegimeConfig(
        trend_intensity_threshold=_f(r["trend"], "trend_intensity_threshold"),
        trend_intensity_strong=_f(r["trend"], "trend_intensity_strong"),
        trend_intensity_min_expansion=_f(r["trend"], "trend_intensity_min_expansion"),
        volatility_baseline_ratio=_f(r["volatility"], "volatility_baseline_ratio"),
        volatility_extreme_ratio=_f(r["volatility"], "volatility_extreme_ratio"),
        volume_surge_vs_ma_ratio=_f(r["volume"], "volume_surge_vs_ma_ratio"),
        long_short_imbalance_ratio=_f(r["imbalance"], "long_short_imbalance_ratio"),
        short_heavy_imbalance_ratio=_f(r["imbalance"], "short_heavy_imbalance_ratio"),
        squeeze_threshold=_f(r["volatility"], "squeeze_threshold"),
        squeeze_audit_threshold=_f(r["volatility"], "squeeze_audit_threshold"),
        ranging_width_atr=_f(r["volatility"], "ranging_width_atr"),
        min_volume_participation_ratio=_f(r["volume"], "min_volume_participation_ratio"),
        vacuum_risk_score=_f(r["volume"], "vacuum_risk_score"),
        wick_skew_exhaustion=_f(r["micro_sentiment"], "wick_skew_exhaustion"),
        cvd_intensity_threshold=_f(r["micro_sentiment"], "cvd_intensity_threshold"),
        cvd_intensity_extreme=_f(r["micro_sentiment"], "cvd_intensity_extreme"),
        funding_extreme_threshold=_f(r["micro_sentiment"], "funding_extreme_threshold"),
        breakout_frontrun_atr=_f(r["structural"], "breakout_frontrun_atr"),
    )


def load_temporal_config(cfg: dict[str, Any]) -> TemporalConfig:
    t = cfg["temporal_parameters"]
    return TemporalConfig(
        min_trade_velocity=_f(t, "min_trade_velocity"),
        temporal_dilation_dead_water=_f(t["dilation"], "temporal_dilation_dead_water"),
        temporal_dilation_highway=_f(t["dilation"], "temporal_dilation_highway"),
        temporal_dilation_climax=_f(t["dilation"], "temporal_dilation_climax"),
        temporal_dilation_standard=_f(t["dilation"], "temporal_dilation_standard"),
        temporal_weight_dead_water=_f(t["weights"], "temporal_weight_dead_water"),
        temporal_weight_highway=_f(t["weights"], "temporal_weight_highway"),
        temporal_weight_climax=_f(t["weights"], "temporal_weight_climax"),
        temporal_weight_standard=_f(t["weights"], "temporal_weight_standard"),
    )


def load_risk_config(cfg: dict[str, Any]) -> RiskConfig:
    risk = cfg["regime_parameters"]["risk"]
    structural = cfg["regime_parameters"]["structural"]
    return RiskConfig(
        min_rr_ranging=_f(risk, "min_rr_ranging"),
        min_rr_trending=_f(risk, "min_rr_trending"),
        structural_buffer_atr=_f(structural, "structural_buffer_atr"),
        stop_loss_buffer_min=_f(risk, "stop_loss_buffer_min"),
        poc_gravity_atr_distance=_f(structural, "poc_gravity_atr_distance"),
        max_entry_distance_atr=_f(structural, "max_entry_distance_atr"),
        chaos_rr_discount=_f(risk, "chaos_rr_discount"),
        structural_proximity_threshold=_f(structural, "structural_proximity_threshold"),
        max_holding_hours=_f(risk, "max_holding_hours"),
    )


def load_audit_config(cfg: dict[str, Any]) -> AuditConfig:
    a = cfg["audit_review"]
    return AuditConfig(
        mae_threshold_pinpoint=_f(a["mae"], "mae_threshold_pinpoint"),
        mae_threshold_standard=_f(a["mae"], "mae_threshold_standard"),
        mae_threshold_luck=_f(a["mae"], "mae_threshold_luck"),
        missed_opportunity_atr_threshold=_f(a, "missed_opportunity_atr_threshold"),
    )


def load_visual_config(cfg: dict[str, Any]) -> VisualConfig:
    import os, yaml
    from src.utils.path_utils import resolve_project_root
    v_path = os.path.join(resolve_project_root(), "config", "visual_config.yaml")
    with open(v_path, "r") as f:
        v = yaml.safe_load(f)
    return VisualConfig(
        volume_profile_width_ratio=_f(v["volume_profile"], "width_ratio"),
        render_dpi=_i(v["chart"], "render_dpi"),
        up_color=_s(v["chart"], "up_color"),
        down_color=_s(v["chart"], "down_color"),
        bg_color=_s(v["chart"], "bg_color"),
        poc_color=_s(v["chart"], "poc_color"),
        vah_val_color=_s(v["chart"], "vah_val_color"),
        current_price_color=_s(v["chart"], "current_price_color"),
    )
