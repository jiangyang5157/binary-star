"""Logical sub-config groupings extracted from monolithic config dataclasses."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeConfig:
    """Market regime thresholds."""
    trend_intensity_threshold: float
    trend_intensity_strong: float
    trend_intensity_min_expansion: float
    volatility_baseline_ratio: float
    volatility_extreme_ratio: float
    volume_surge_vs_ma_ratio: float
    long_short_imbalance_ratio: float
    short_heavy_imbalance_ratio: float
    squeeze_threshold: float
    squeeze_audit_threshold: float
    ranging_width_atr: float
    min_volume_participation_ratio: float
    vacuum_risk_score: float
    wick_skew_exhaustion: float
    cvd_intensity_threshold: float
    cvd_intensity_extreme: float
    funding_extreme_threshold: float
    breakout_frontrun_atr: float


@dataclass(frozen=True)
class TemporalConfig:
    """Time dilation and velocity parameters."""
    min_trade_velocity: float
    temporal_dilation_dead_water: float
    temporal_dilation_highway: float
    temporal_dilation_climax: float
    temporal_dilation_standard: float
    temporal_weight_dead_water: float
    temporal_weight_highway: float
    temporal_weight_climax: float
    temporal_weight_standard: float


@dataclass(frozen=True)
class RiskConfig:
    """Risk-reward and structural protection thresholds."""
    min_rr_ranging: float
    min_rr_trending: float
    structural_buffer_atr: float
    stop_loss_buffer_min: float
    poc_gravity_atr_distance: float
    max_entry_distance_atr: float
    chaos_rr_discount: float
    max_holding_hours: float


@dataclass(frozen=True)
class AuditConfig:
    """Forensic audit thresholds."""
    mae_threshold_pinpoint: float
    mae_threshold_standard: float
    mae_threshold_luck: float
    missed_opportunity_atr_threshold: float


@dataclass(frozen=True)
class VisualConfig:
    """Chart rendering parameters."""
    volume_profile_width_ratio: float
    render_dpi: int
    up_color: str
    down_color: str
    bg_color: str
    poc_color: str
    vah_val_color: str
    current_price_color: str
