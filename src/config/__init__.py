"""Config consolidation package.

Sub-config dataclasses and loaders extracted from monolithic agent configs.
"""
from src.config.sub_configs import (
    RegimeConfig,
    TemporalConfig,
    RiskConfig,
    AuditConfig,
    VisualConfig,
)
from src.config.loader import (
    load_regime_config,
    load_temporal_config,
    load_risk_config,
    load_audit_config,
    load_visual_config,
)

__all__ = [
    "RegimeConfig",
    "TemporalConfig",
    "RiskConfig",
    "AuditConfig",
    "VisualConfig",
    "load_regime_config",
    "load_temporal_config",
    "load_risk_config",
    "load_audit_config",
    "load_visual_config",
]
