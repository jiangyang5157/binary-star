"""Regime state pre-computation for Binary Star agents.

Pure functions that compute boolean macro states from structured inputs.
Replaces the LOGIC_MACROS sections in the four prompt files.

All functions return dict[str, bool] — keyed by UPPER_SNAKE_CASE macro names.
"""

from __future__ import annotations

import json
from typing import Any


def _format_states(states: dict[str, bool]) -> str:
    """JSON-formatted states block for prompt injection."""
    return json.dumps(states, indent=2)


def compute_time_calibration(
    audit_reports: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-regime signed time error from TP_HIT trades only.

    For each regime (highway/standard/dead_water/climax), collects the
    percentage difference between actual and projected holding hours for
    every TP_HIT trade and reports the mean signed error.

    Positive error → trades took longer than projected (dilation too tight).
    Negative error → trades finished faster than projected (dilation too loose).
    """
    # Short alias for the config key
    regime_keys = [
        "temporal_dilation_highway",
        "temporal_dilation_standard",
        "temporal_dilation_dead_water",
        "temporal_dilation_climax",
    ]
    errors: dict[str, list[float]] = {k: [] for k in regime_keys}

    for r in audit_reports:
        outcome = r.get("market_outcome", {})
        if outcome.get("tp_sl_result") != "TP_HIT":
            continue
        metrics = outcome.get("trade_execution_metrics", {})
        actual = metrics.get("actual_holding_hours")
        projected = metrics.get("projected_holding_hours")
        regime = metrics.get("temporal_dilation_regime", "")
        if (
            actual is not None
            and projected is not None
            and projected > 0
            and regime in errors
        ):
            error_pct = (actual - projected) / projected * 100
            errors[regime].append(error_pct)

    report: dict[str, dict[str, Any]] = {}
    for regime in regime_keys:
        vals = errors[regime]
        n = len(vals)
        report[regime] = {
            "avg_time_error_pct": round(sum(vals) / n, 1) if n > 0 else None,
            "samples": n,
        }
    return report


# ── Shared 12 regime states ───────────────────────────────────

def compute_shared_regime_states(
    observation: dict[str, Any],
    regime_config,  # RegimeConfig
) -> dict[str, bool]:
    """Compute 12 shared market regime states from observation telemetry."""
    metrics = observation.get("quantitative_metrics", {})
    price_dyn = metrics.get("price_dynamics", {})
    market_reg = metrics.get("market_regime", {})
    sentiment = metrics.get("sentiment_signals", {})

    vol_exp_idx = float(price_dyn.get("volatility_expansion_index", 1.0))
    squeeze = float(market_reg.get("squeeze_factor", 1.0))
    trend = float(market_reg.get("trend_intensity", 0.0))
    vol_part = float(market_reg.get("volume_participation_ratio", 1.0))
    cvd = float(sentiment.get("cvd_intensity_ratio", 0.0))
    ls_micro = float(sentiment.get("ls_ratio_micro", 1.0))
    oi_delta = float(sentiment.get("oi_delta_micro", 0.0))

    is_expanding = vol_exp_idx > regime_config.volatility_baseline_ratio
    is_chaos = vol_exp_idx > regime_config.volatility_extreme_ratio
    is_trend = abs(trend) >= regime_config.trend_intensity_threshold
    is_trend_strong = abs(trend) > regime_config.trend_intensity_strong

    return {
        "IS_EXPANDING": is_expanding,
        "IS_CHAOS": is_chaos,
        "IS_SQUEEZING": squeeze < regime_config.squeeze_threshold,
        "IS_TREND": is_trend,
        "IS_TREND_STRONG": is_trend_strong,
        "HAS_VOLUME_SURGE": vol_part > regime_config.min_volume_participation_ratio,
        "HAS_CVD_MOMENTUM": abs(cvd) > regime_config.cvd_intensity_threshold,
        "HAS_BULL_FLOW": cvd > regime_config.cvd_intensity_threshold,
        "HAS_BEAR_FLOW": cvd < -regime_config.cvd_intensity_threshold,
        "HAS_RETAIL_LONG_IMBALANCE": ls_micro > regime_config.long_short_imbalance_ratio,
        "HAS_RETAIL_SHORT_IMBALANCE": ls_micro < regime_config.short_heavy_imbalance_ratio,
        "HAS_ABSORPTION_RISK": (oi_delta < 0 and abs(cvd) > regime_config.cvd_intensity_extreme),
    }


# ── Session 3 states ─────────────────────────────────────────

def compute_session_states(
    debate_history: list[dict[str, Any]] | None,
) -> dict[str, bool]:
    """Compute 3 session-specific states from debate history."""
    is_planning = debate_history is None
    is_synthesis = debate_history is not None

    has_terminal_veto = False
    if debate_history:
        for entry in debate_history:
            critic = entry.get("critic", {})
            if isinstance(critic, dict):
                if (critic.get("veto_level") or "").upper() == "TERMINAL":
                    has_terminal_veto = True
                    break

    return {
        "IS_PLANNING": is_planning,
        "IS_SYNTHESIS": is_synthesis,
        "HAS_TERMINAL_VETO": has_terminal_veto,
    }


# ── Critic 16 states ─────────────────────────────────────────

def _parse_opinion(plan: dict[str, Any]) -> str:
    return (plan.get("opinion") or "NEUTRAL").upper()


def compute_critic_states(
    observation: dict[str, Any],
    last_plan: dict[str, Any],
    math_fact_check: dict[str, Any] | None,
    regime_config,  # RegimeConfig
    risk_config,    # RiskConfig
) -> dict[str, bool]:
    """Compute 16 critic-specific states. Excludes HAS_PROTOCOL_VIOLATION (LLM-judged).

    Each function is self-contained — shared states (IS_TREND_STRONG, etc.)
    are recomputed inline rather than passed in, keeping modules decoupled.
    """
    if math_fact_check is None:
        math_fact_check = {}

    metrics = observation.get("quantitative_metrics", {})
    price_dyn = metrics.get("price_dynamics", {})
    market_reg = metrics.get("market_regime", {})
    sentiment = metrics.get("sentiment_signals", {})
    volume_prof = metrics.get("volume_profile", {})
    struct_anch = metrics.get("structural_anchors", {})

    tactical = last_plan.get("tactical_parameters", {})
    compliance = math_fact_check.get("compliance_verdict", {})
    holding = math_fact_check.get("holding_time_verification", {})

    opinion = _parse_opinion(last_plan)
    entry = float(tactical.get("entry", 0) or 0)
    sl = float(tactical.get("stop_loss", 0) or 0)
    current_price = float(tactical.get("current_price", 0) or 0)
    proj_hold = float(tactical.get("projected_holding_hours", 0) or 0)

    cvd = float(sentiment.get("cvd_intensity_ratio", 0.0))
    trend = float(market_reg.get("trend_intensity", 0.0))
    poc_dist = float(struct_anch.get("poc_dist_atr", 0.0))
    ls_micro = float(sentiment.get("ls_ratio_micro", 1.0))
    funding = float(sentiment.get("funding_rate", 0.0))
    squeeze = float(market_reg.get("squeeze_factor", 1.0))
    vol_exp_idx = float(price_dyn.get("volatility_expansion_index", 1.0))

    # Self-contained shared state derivations (decoupled from compute_shared_regime_states)
    is_trend_strong = abs(trend) > regime_config.trend_intensity_strong
    is_expanding = vol_exp_idx > regime_config.volatility_baseline_ratio
    is_squeezing = squeeze < regime_config.squeeze_threshold

    # Basic plan states
    is_bullish = opinion == "BULLISH"
    is_bearish = opinion == "BEARISH"
    in_neutral = opinion == "NEUTRAL"

    # Entry/sl safety
    is_entry_safe = (
        (is_bullish and entry <= current_price)
        or (is_bearish and entry >= current_price)
    )
    is_sl_logical = (
        (is_bullish and sl < entry)
        or (is_bearish and sl > entry)
    )

    # From math_fact_check
    is_sl_shielded = bool(compliance.get("sl_is_shielded", False))
    is_rr_valid = bool(compliance.get("rr_is_valid", False))

    # Sentiment
    has_bear_sentiment = (
        ls_micro > regime_config.long_short_imbalance_ratio
        or funding > regime_config.funding_extreme_threshold
    )
    has_bull_sentiment = (
        ls_micro < regime_config.short_heavy_imbalance_ratio
        or funding < -regime_config.funding_extreme_threshold
    )

    # Flow
    has_cvd_momentum = abs(cvd) > regime_config.cvd_intensity_threshold
    has_flow_opposition = (
        (cvd > regime_config.cvd_intensity_threshold and is_bearish)
        or (cvd < -regime_config.cvd_intensity_threshold and is_bullish)
        or (trend > regime_config.trend_intensity_strong and is_bearish)
        or (trend < -regime_config.trend_intensity_strong and is_bullish)
    )

    # Overextending
    is_overextending = (
        abs(poc_dist) > risk_config.poc_gravity_atr_distance
        and (
            (poc_dist > 0 and is_bullish)
            or (poc_dist < 0 and is_bearish)
        )
        and not (is_trend_strong and has_cvd_momentum)
    )

    # Holding too long
    temporal_weight = float(holding.get("temporal_weight_factor", 1.0))
    is_holding_too_long = proj_hold > (risk_config.max_holding_hours * temporal_weight)

    # Volatility chop
    is_volatility_chop = (
        is_expanding
        and abs(trend) < regime_config.trend_intensity_min_expansion
        and not is_squeezing
    )

    # Liquidity void
    nearest_lvn = float(volume_prof.get("nearest_lvn_dist_atr", 999.0))
    has_liquidity_void = nearest_lvn < risk_config.structural_buffer_atr

    # Structural trap — entry near an LVN with high vacuum_score
    is_structural_trap = False
    if entry > 0:
        anchors_above = volume_prof.get("anchors_above", []) or []
        anchors_below = volume_prof.get("anchors_below", []) or []
        all_nodes = anchors_above + anchors_below
        closest_node = None
        closest_dist = float("inf")
        for node in all_nodes:
            node_price = float(node.get("price", 0))
            dist = abs(node_price - entry)
            if dist < closest_dist:
                closest_dist = dist
                closest_node = node
        if closest_node and closest_node.get("type") == "LVN":
            vacuum = float(closest_node.get("vacuum_score", 0))
            if vacuum > regime_config.vacuum_risk_score:
                is_structural_trap = True

    # Anchor violation
    has_anchor_violation = False
    if not in_neutral:
        proximity = math_fact_check.get("structural_armor_verification", {})
        prox_values = [float(v) for v in proximity.values()
                       if v is not None and isinstance(v, (int, float))]
        # sl_shielded check: for BULLISH, any negative proximity means anchor is below sl
        sl_is_protected = (
            any(v < -risk_config.structural_buffer_atr for v in prox_values)
            if is_bullish
            else any(v > risk_config.structural_buffer_atr for v in prox_values)
        )
        anchor_between_violation = (
            not is_trend_strong
            and (not is_sl_shielded or not sl_is_protected)
        )
        if anchor_between_violation:
            has_anchor_violation = True

        # Liquidation cluster proximity check
        # A cluster between entry and SL is a real cascade risk —
        # price sweeping through it can overrun the stop.
        liq_clusters = sentiment.get("liquidation_clusters", {}) or {}
        for cluster_list in liq_clusters.values():
            if not isinstance(cluster_list, list):
                continue
            for cluster in cluster_list:
                cluster_price = float(cluster.get("price", 0))
                if cluster_price <= 0:
                    continue
                if (
                    (is_bullish and sl <= cluster_price < entry)
                    or (is_bearish and entry < cluster_price <= sl)
                ):
                    has_anchor_violation = True
                    break
            if has_anchor_violation:
                break

    return {
        "IS_BULLISH": is_bullish,
        "IS_BEARISH": is_bearish,
        "IN_NEUTRAL": in_neutral,
        "HAS_BEAR_SENTIMENT": has_bear_sentiment,
        "HAS_BULL_SENTIMENT": has_bull_sentiment,
        "IS_SL_SHIELDED": is_sl_shielded,
        "IS_RR_VALID": is_rr_valid,
        "IS_ENTRY_SAFE": is_entry_safe,
        "IS_SL_LOGICAL": is_sl_logical,
        "IS_OVEREXTENDING": is_overextending,
        "IS_HOLDING_TOO_LONG": is_holding_too_long,
        "HAS_FLOW_OPPOSITION": has_flow_opposition,
        "IS_VOLATILITY_CHOP": is_volatility_chop,
        "HAS_LIQUIDITY_VOID": has_liquidity_void,
        "IS_STRUCTURAL_TRAP": is_structural_trap,
        "HAS_ANCHOR_VIOLATION": has_anchor_violation,
    }


# ── Evolver 7 states ─────────────────────────────────────────

def compute_evolver_states(
    audit_reports: list[dict[str, Any]],
    audit_config,  # AuditConfig
) -> dict[str, Any]:
    """Compute batch-level evolver states and time calibration from audit reports."""
    total = len(audit_reports)
    if total == 0:
        empty_regimes = {
            "temporal_dilation_highway": {"avg_time_error_pct": None, "samples": 0},
            "temporal_dilation_standard": {"avg_time_error_pct": None, "samples": 0},
            "temporal_dilation_dead_water": {"avg_time_error_pct": None, "samples": 0},
            "temporal_dilation_climax": {"avg_time_error_pct": None, "samples": 0},
        }
        return {
            "IS_BATCH_SIGNIFICANT": False,
            "IS_FAILURE_RATIO_ALARM": False,
            "HAS_SYSTEMIC_PATHOLOGY": False,
            "IS_LOGIC_COWARDICE": False,
            "HAS_STRUCTURAL_AMNESTY": False,
            "IS_PROFIT_EVAPORATION": False,
            "IS_CATASTROPHIC_NEUTRAL_MISS": False,
            "IS_CATASTROPHIC_UNFILLED_MISS": False,
            "fill_rate_pct": 0,
            "near_miss_rate": 0,
            "mae_stress_distribution": {"PINPOINT": 0, "STANDARD": 0, "LUCK": 0, "FAILURE": 0},
            "cowardice_tag_rate": 0,
            "time_calibration_report": empty_regimes,
        }

    non_profit = sum(
        1 for r in audit_reports
        if (r.get("market_outcome", {}).get("tp_sl_result") or "").upper() != "TP_HIT"
    )
    is_batch_significant = non_profit >= 2
    is_failure_ratio_alarm = (non_profit / total) > 0.2
    has_systemic_pathology = is_batch_significant and is_failure_ratio_alarm

    # IS_LOGIC_COWARDICE: NEUTRAL sessions where Critic gave specific tags
    cowardice_tags = {"[INACTION_BIAS]", "[TREND_STARVATION]", "[OPPORTUNITY_DENIAL]"}
    is_logic_cowardice = False
    for r in audit_reports:
        session = r.get("session", {})
        opinion = (session.get("final_decision", {}).get("opinion") or "").upper()
        if opinion != "NEUTRAL":
            continue
        history = session.get("debate_history", []) or []
        for entry in history:
            critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
            invalids = critic.get("invalidations", []) or []
            for inv in invalids:
                tag = str(inv).split(" - ")[0].strip() if " - " in str(inv) else str(inv)
                if tag in cowardice_tags:
                    is_logic_cowardice = True
                    break
            if is_logic_cowardice:
                break
        if is_logic_cowardice:
            break

    # HAS_STRUCTURAL_AMNESTY: any filled report where last math_fact_check
    # confirms sl_shielded AND mae_stress_tier is STANDARD.
    has_structural_amnesty = False
    for r in audit_reports:
        outcome = r.get("market_outcome", {})
        if not outcome.get("is_filled"):
            continue
        session = r.get("session", {})
        history = session.get("debate_history", []) or []
        last_mfc = {}
        if history:
            last_entry = history[-1] if isinstance(history[-1], dict) else {}
            last_mfc = last_entry.get("math_fact_check", {}) or {}
        sl_shielded = last_mfc.get("compliance_verdict", {}).get("sl_is_shielded", False)
        mae_tier = (outcome.get("trade_execution_metrics", {}).get("mae_stress_tier") or "").upper()
        if sl_shielded and mae_tier == "STANDARD":
            has_structural_amnesty = True
            break

    # IS_PROFIT_EVAPORATION: outcome=NEITHER AND MFE >= 60% of TP distance.
    # NEUTRAL sessions excluded — no position was entered, no profit to evaporate.
    is_profit_evaporation = False
    for r in audit_reports:
        outcome = r.get("market_outcome", {})
        if (outcome.get("tp_sl_result") or "").upper() != "NEITHER":
            continue
        session = r.get("session", {})
        opinion = (session.get("final_decision", {}).get("opinion") or "").upper()
        if opinion == "NEUTRAL":
            continue
        mfe_atr = float(outcome.get("market_forensics", {}).get("max_favorable_runup_atr", 0))
        tp_params = session.get("final_decision", {}).get("tactical_parameters", {})
        entry = float(tp_params.get("entry") or 0)
        tp = float(tp_params.get("take_profit") or 0)
        atr = float(session.get("observation", {}).get("quantitative_metrics", {}).get("price_dynamics", {}).get("atr_macro", 1.0))
        tp_distance_atr = abs(tp - entry) / atr if atr > 0 else 1.0
        if mfe_atr >= 0.6 * tp_distance_atr:
            is_profit_evaporation = True
            break

    # ── Batch forensic stats ─────────────────────────────────────

    # fill_rate_pct: directional session fill rate
    directional = [r for r in audit_reports
        if (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() != "NEUTRAL"]
    filled = [r for r in directional
        if r.get("market_outcome", {}).get("is_filled")]
    fill_rate_pct = round(len(filled) / len(directional) * 100, 1) if directional else 0

    # near_miss_rate: of unfilled sessions, % where entry was close to filling
    unfilled = [r for r in directional
        if not r.get("market_outcome", {}).get("is_filled")]
    near_miss = [r for r in unfilled
        if r.get("market_outcome", {}).get("execution_forensics", {}).get("is_near_miss")]
    near_miss_rate = round(len(near_miss) / len(unfilled) * 100, 1) if unfilled else 0

    # mae_stress_distribution: counts per tier across filled trades only
    distribution = {"PINPOINT": 0, "STANDARD": 0, "LUCK": 0, "FAILURE": 0}
    for r in audit_reports:
        if not r.get("market_outcome", {}).get("is_filled"):
            continue
        tier = (r.get("market_outcome", {}).get("trade_execution_metrics", {}) or {}).get("mae_stress_tier", "")
        if tier in distribution:
            distribution[tier] += 1
    mae_stress_distribution = distribution

    # cowardice_tag_rate: % of NEUTRAL sessions where Critic flagged inaction
    neutral_sessions = [r for r in audit_reports
        if (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() == "NEUTRAL"]
    cowardice_count = 0
    for r in neutral_sessions:
        history = r.get("session", {}).get("debate_history", []) or []
        for entry in history:
            critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
            for inv in (critic.get("invalidations", []) or []):
                tag = str(inv).split(" - ")[0].strip() if " - " in str(inv) else str(inv)
                if tag in cowardice_tags:
                    cowardice_count += 1
                    break
            else:
                continue
            break
    cowardice_tag_rate = round(cowardice_count / len(neutral_sessions) * 100, 1) if neutral_sessions else 0

    # IS_CATASTROPHIC_MISS split: NEUTRAL (sat out) vs directional unfilled (couldn't reach entry)
    is_catastrophic_neutral_miss = any(
        (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() == "NEUTRAL"
        and r.get("market_outcome", {}).get("forensic_verdict", {}).get("is_catastrophic_miss") is True
        for r in audit_reports
    )

    is_catastrophic_unfilled_miss = any(
        (r.get("session", {}).get("final_decision", {}).get("opinion") or "").upper() != "NEUTRAL"
        and not r.get("market_outcome", {}).get("is_filled")
        and r.get("market_outcome", {}).get("forensic_verdict", {}).get("is_catastrophic_miss") is True
        for r in audit_reports
    )

    # Time calibration
    time_cal = compute_time_calibration(audit_reports)

    return {
        "IS_BATCH_SIGNIFICANT": is_batch_significant,
        "IS_FAILURE_RATIO_ALARM": is_failure_ratio_alarm,
        "HAS_SYSTEMIC_PATHOLOGY": has_systemic_pathology,
        "IS_LOGIC_COWARDICE": is_logic_cowardice,
        "HAS_STRUCTURAL_AMNESTY": has_structural_amnesty,
        "IS_PROFIT_EVAPORATION": is_profit_evaporation,
        "IS_CATASTROPHIC_NEUTRAL_MISS": is_catastrophic_neutral_miss,
        "IS_CATASTROPHIC_UNFILLED_MISS": is_catastrophic_unfilled_miss,
        "fill_rate_pct": fill_rate_pct,
        "near_miss_rate": near_miss_rate,
        "mae_stress_distribution": mae_stress_distribution,
        "cowardice_tag_rate": cowardice_tag_rate,
        "time_calibration_report": time_cal,
    }
