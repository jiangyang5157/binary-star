"""Unified symbol-aware config resolution and patching.

All config consumers should use this module for symbol-specific resolution.
The resolution order is: base config + symbol.overrides → resolved config.
Symbol overrides always win on conflict.
"""
import copy
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.utils.path_utils import resolve_project_root


# ── Internal helpers ────────────────────────────────────────────────────────

def _deep_merge(base: dict, overrides: dict) -> None:
    """Mutates base by merging overrides recursively (in-place)."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _load_yaml(rel_path: str) -> dict:
    """Load a YAML file relative to the project root."""
    path = os.path.join(resolve_project_root(), rel_path)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Public API ──────────────────────────────────────────────────────────────

def load_symbol_config() -> dict:
    """Load symbol_config.yaml → {SYMBOL: {precision_qty, ..., overrides: {...}}}."""
    return _load_yaml("config/symbol_config.yaml")


def list_configured_symbols() -> List[str]:
    """Return all symbol names defined in symbol_config.yaml."""
    return list(load_symbol_config().keys())


def get_symbol_trade_params(symbol: str) -> Dict[str, Any]:
    """Return execution parameters for a symbol.

    Returns {precision_qty, precision_price, min_order_qty, sl_slippage_buffer}.
    Falls back to defaults if the symbol is not configured.
    """
    sym_cfg = load_symbol_config().get(symbol, {})
    return {
        "precision_qty": sym_cfg.get("precision_qty", 4),
        "precision_price": sym_cfg.get("precision_price", 1),
        "min_order_qty": sym_cfg.get("min_order_qty", 0.001),
        "sl_slippage_buffer": sym_cfg.get("sl_slippage_buffer", 0.0),
    }


def resolve_config(base_config: dict, symbol: str, symbol_config: Optional[dict] = None) -> dict:
    """Deep-merge symbol overrides into a copy of base_config.

    Resolution: base_config + symbol.overrides → resolved (symbol wins).
    If the symbol has no overrides or is not configured, returns a deep copy
    of base_config unchanged.

    Args:
        base_config: The base config dict (e.g., strategy_config.yaml content).
        symbol: The trading symbol (e.g., "XAUTUSDT").
        symbol_config: Optional pre-loaded symbol_config dict (avoids re-read).

    Returns a new dict; does not mutate inputs.
    """
    result = copy.deepcopy(base_config)

    if symbol_config is None:
        symbol_config = load_symbol_config()

    sym_cfg = symbol_config.get(symbol, {})
    overrides = sym_cfg.get("overrides", {})

    if isinstance(overrides, dict) and overrides:
        for section, section_overrides in overrides.items():
            if not isinstance(section_overrides, dict):
                continue
            if section in result and isinstance(result[section], dict):
                _deep_merge(result[section], section_overrides)

    return result


def resolve_all(symbol: str) -> Dict[str, Any]:
    """Load and resolve ALL base configs for a symbol.

    Loads strategy_config.yaml + global_config.yaml, deep-merges them
    (strategy takes priority on conflicts), then applies symbol overrides.

    Returns a single merged + resolved dict suitable for most consumers.
    """
    from src.utils.pipeline_utils import load_config, load_global_config

    strategy = load_config()
    global_cfg = load_global_config()

    # Merge base configs: global + strategy (strategy wins on conflict)
    base = copy.deepcopy(global_cfg)
    _deep_merge(base, strategy)

    # Apply symbol overrides
    return resolve_config(base, symbol)


def is_symbol_configured(symbol: str) -> bool:
    """Check if a symbol is defined in symbol_config.yaml."""
    return symbol in load_symbol_config()


def patch_config(symbol: str, target_path: str, key: str, value: Any) -> int:
    """Patch a config value, writing to symbol overrides first, then base config.

    Resolution order:
    1. If key exists in symbol_config.yaml → <SYMBOL>.overrides.<target_path> → patch there
    2. Else → patch strategy_config.yaml (existing behavior)

    Args:
        symbol: Trading symbol (e.g., "XAUTUSDT").
        target_path: Dot-notation path to the parent section (e.g., "regime_parameters.trend").
        key: The config key name.
        value: New value to write.

    Returns number of keys updated (0 or 1).
    """
    from ruamel.yaml import YAML

    symbol_path = os.path.join(resolve_project_root(), "config", "symbol_config.yaml")
    strategy_path = os.path.join(resolve_project_root(), "config", "strategy_config.yaml")

    if not os.path.exists(symbol_path):
        # Fall back to strategy_config.yaml only
        from src.utils.evolution_utils import ConfigPatcher
        return ConfigPatcher.apply_patch(strategy_path, key, value, target_path)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    with open(symbol_path, "r", encoding="utf-8") as f:
        sym_cfg = yaml.load(f)

    # Navigate to symbol.overrides.<target_path>
    sym_node = sym_cfg.get(symbol, {})
    overrides_node = sym_node.get("overrides", {})

    if not isinstance(overrides_node, dict):
        overrides_node = {}
        sym_node["overrides"] = overrides_node

    # Navigate target_path segments within overrides
    curr = overrides_node
    if target_path:
        parts = target_path.split(".")
        for part in parts:
            if part not in curr or not isinstance(curr[part], dict):
                curr[part] = {}
            curr = curr[part]

    # Check if key exists at the navigated position
    if key in curr:
        curr[key] = value
        with open(symbol_path, "w", encoding="utf-8") as f:
            yaml.dump(sym_cfg, f)
        return 1

    # Key not in overrides — fall back to strategy_config.yaml
    from src.utils.evolution_utils import ConfigPatcher
    return ConfigPatcher.apply_patch(strategy_path, key, value, target_path)
