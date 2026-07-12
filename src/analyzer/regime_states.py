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


# ── Shared 12 macros (binary_star.md §5) ─────────────────────

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


# ── Session 3 macros ─────────────────────────────────────────

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


# ── Critic 16 macros ─────────────────────────────────────────

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
        liq_clusters = sentiment.get("liquidation_clusters", {}) or {}
        for cluster_list in liq_clusters.values():
            if not isinstance(cluster_list, list):
                continue
            for cluster in cluster_list:
                cluster_price = float(cluster.get("price", 0))
                if cluster_price <= 0:
                    continue
                if (
                    (is_bullish and sl >= cluster_price)
                    or (is_bearish and sl <= cluster_price)
                ):
                    # sl is at or beyond a liquidation cluster
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


# ── Evolver 7 macros ─────────────────────────────────────────

def compute_evolver_states(
    audit_reports: list[dict[str, Any]],
    audit_config,  # AuditConfig
) -> dict[str, bool]:
    """Compute 7 batch-level evolver states from audit reports."""
    total = len(audit_reports)
    if total == 0:
        return {
            "IS_BATCH_SIGNIFICANT": False,
            "IS_FAILURE_RATIO_ALARM": False,
            "HAS_SYSTEMIC_PATHOLOGY": False,
            "IS_LOGIC_COWARDICE": False,
            "HAS_STRUCTURAL_AMNESTY": False,
            "IS_PROFIT_EVAPORATION": False,
            "IS_CATASTROPHIC_MISS": False,
        }

    non_profit = sum(
        1 for r in audit_reports
        if (r.get("outcome") or "").upper() != "PROFIT"
    )
    is_batch_significant = non_profit >= 2
    is_failure_ratio_alarm = (non_profit / total) > 0.2
    has_systemic_pathology = is_batch_significant and is_failure_ratio_alarm

    # IS_LOGIC_COWARDICE: NEUTRAL sessions where Critic gave specific tags
    cowardice_tags = {"[INACTION_BIAS]", "[TREND_STARVATION]", "[OPPORTUNITY_DENIAL]"}
    is_logic_cowardice = False
    for r in audit_reports:
        opinion = (r.get("opinion") or "").upper()
        if opinion != "NEUTRAL":
            continue
        history = r.get("debate_history", []) or []
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

    # HAS_STRUCTURAL_AMNESTY: any report with sl_shielded + STANDARD tier
    has_structural_amnesty = any(
        r.get("sl_is_shielded") is True
        and (r.get("mae_stress_tier") or "").upper() == "STANDARD"
        for r in audit_reports
    )

    # IS_PROFIT_EVAPORATION: outcome=NEITHER AND MFE >= 60% of TP distance
    is_profit_evaporation = any(
        (r.get("outcome") or "").upper() == "NEITHER"
        and float(r.get("mfe_atr", 0)) >= 0.6 * float(r.get("tp_distance_atr", 1.0))
        for r in audit_reports
    )

    # IS_CATASTROPHIC_MISS: NEUTRAL or unfilled + market moved beyond target
    is_catastrophic_miss = any(
        (
            (r.get("outcome") or "").upper() in ("NEUTRAL", "UNFILLED")
        )
        and float(r.get("mfe_atr", 0)) > float(r.get("tp_distance_atr", 1.0))
        for r in audit_reports
    )

    return {
        "IS_BATCH_SIGNIFICANT": is_batch_significant,
        "IS_FAILURE_RATIO_ALARM": is_failure_ratio_alarm,
        "HAS_SYSTEMIC_PATHOLOGY": has_systemic_pathology,
        "IS_LOGIC_COWARDICE": is_logic_cowardice,
        "HAS_STRUCTURAL_AMNESTY": has_structural_amnesty,
        "IS_PROFIT_EVAPORATION": is_profit_evaporation,
        "IS_CATASTROPHIC_MISS": is_catastrophic_miss,
    }
