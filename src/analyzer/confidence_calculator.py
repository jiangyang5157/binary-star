"""Confidence calculator — deterministic survival-probability scoring.

Replaces the LLM-evaluated Confidence Calculus in session.md.
One public entry point, each dimension a private function for easy tuning.
"""

from __future__ import annotations
from typing import Any

# ── Module-level thresholds (single-point tuning) ──────────────

_ANCHOR_STRONG = 0.8
_ANCHOR_MODERATE = 0.5
_BETWEENNESS_GAP_ATR = 0.3
_ENTRY_PROXIMITY_TIGHT = 0.5
_ENTRY_PROXIMITY_LOOSE = 1.2
_GRAVITY_CAP_MAX = 5.0
_HOLDING_RATIO_IDEAL_LO = 0.7
_HOLDING_RATIO_IDEAL_HI = 1.5
_WAIT_HOLD_TIGHT = 0.15
_WAIT_HOLD_OK = 0.30
_WAIT_HOLD_MAX = 0.50
_DEBATE_TERMINAL_PARADIGM = 10.0
_DEBATE_TERMINAL_COSMETIC = 20.0
_DEBATE_CONSTRUCTIVE_STALE_MIN = 5.0
_DEBATE_CONSTRUCTIVE_STALE_MAX = 10.0
_ANCHOR_DISTANT_ATR = 2.0
_CLUSTER_PENALTY = 3.0
_FUNDING_AGAINST_PENALTY = 2.0
_SENTIMENT_SCORE_BALANCED = 7.0
_SENTIMENT_SCORE_ALIGNED_LO = 4.0
_SENTIMENT_SCORE_ALIGNED_HI = 6.0
_SENTIMENT_SCORE_AGAINST_LO = 0.0
_SENTIMENT_SCORE_AGAINST_HI = 2.0
_FLOW_BOTH_STRONG = 10.0
_FLOW_ONE_STRONG_LO = 5.0
_FLOW_ONE_STRONG_HI = 8.0
_FLOW_NEUTRAL_LO = 2.0
_FLOW_NEUTRAL_HI = 4.0
_REGIME_CANONICAL = 10.0
_REGIME_DEFENSIBLE_LO = 4.0
_REGIME_DEFENSIBLE_HI = 7.0
_REGIME_MISMATCH_LO = 0.0
_REGIME_MISMATCH_HI = 3.0
_TP_PROPORTIONAL_FIRST_BOUNDARY = 5.0
_TP_PROPORTIONAL_NORMAL_LO = 3.0
_TP_PROPORTIONAL_NORMAL_HI = 4.0
_TP_PROPORTIONAL_EXCESSIVE_LO = 0.0
_TP_PROPORTIONAL_EXCESSIVE_HI = 2.0
_POLARITY_ALL = 5.0
_POLARITY_MINOR_LO = 2.0
_POLARITY_MINOR_HI = 4.0
_POLARITY_MAJOR = 0.0
_HOLDING_IDEAL_LO = 8.0
_HOLDING_IDEAL_HI = 10.0
_HOLDING_OK_LO = 4.0
_HOLDING_OK_HI = 7.0
_HOLDING_BAD_LO = 1.0
_HOLDING_BAD_HI = 3.0
_WAIT_TIGHT = 8.0
_WAIT_OK_LO = 5.0
_WAIT_OK_HI = 7.0
_WAIT_LOOSE_LO = 2.0
_WAIT_LOOSE_HI = 4.0
_WAIT_LONG_LO = 0.0
_WAIT_LONG_HI = 1.0
_SQUEEZE_TIGHT = 5.0
_SQUEEZE_LOOSE_LO = 2.0
_SQUEEZE_LOOSE_HI = 3.0
_BETWEENNESS_PERFECT = 10.0
_BETWEENNESS_ADJACENT_LO = 5.0
_BETWEENNESS_ADJACENT_HI = 8.0
_BETWEENNESS_DKS_LO = 3.0
_BETWEENNESS_DKS_HI = 5.0
_PROXIMITY_TIGHT = 5.0
_PROXIMITY_OK_LO = 3.0
_PROXIMITY_OK_HI = 4.0
_PROXIMITY_LOOSE_LO = 1.0
_PROXIMITY_LOOSE_HI = 2.0
_ANCHOR_STRONG_LO = 12.0
_ANCHOR_STRONG_HI = 15.0
_ANCHOR_MODERATE_LO = 8.0
_ANCHOR_MODERATE_HI = 11.0
_ANCHOR_WEAK_LO = 3.0
_ANCHOR_WEAK_HI = 7.0
_VACUUM_HVN = 5.0
_VACUUM_LVN_LO = 3.0
_VACUUM_LVN_HI = 4.0
_VACUUM_NEAR_HVN_LO = 1.0
_VACUUM_NEAR_HVN_HI = 2.0
_MULTI_STRONG = 5.0
_MULTI_WEAK_LO = 2.0
_MULTI_WEAK_HI = 3.0
_MULTI_FAR_ATR = 3.0


# ── Public entry point ────────────────────────────────────────

def compute_confidence(
    plan: dict[str, Any],
    observation: dict[str, Any],
    math_fact_check: dict[str, Any],
    debate_history: list[dict[str, Any]] | None,
    regime_config,   # RegimeConfig
    risk_config,      # RiskConfig
) -> float:
    """Compute confidence_score [0, 100].

    Zero-score conditions: NEUTRAL opinion, rr_is_valid == False, atr <= 0.
    """
    opinion = (plan.get("opinion") or "NEUTRAL").upper()
    if opinion == "NEUTRAL":
        return 0.0

    compliance = math_fact_check.get("compliance_verdict", {})
    if compliance.get("rr_is_valid") is False:
        return 0.0

    tactical = plan.get("tactical_parameters", {})
    entry = float(tactical.get("entry", 0) or 0)
    sl = float(tactical.get("stop_loss", 0) or 0)
    tp = float(tactical.get("take_profit", 0) or 0)
    current_price = float(tactical.get("current_price", 0) or 0)
    proj_holding = float(tactical.get("projected_holding_hours", 0) or 0)
    proj_waiting = float(tactical.get("projected_waiting_hours", 0) or 0)

    metrics = observation.get("quantitative_metrics", {})
    price_dyn = metrics.get("price_dynamics", {})
    market_reg = metrics.get("market_regime", {})
    sentiment = metrics.get("sentiment_signals", {})
    volume_prof = metrics.get("volume_profile", {})

    atr = float(price_dyn.get("atr_macro", 0) or 0)
    if atr <= 0:
        return 0.0

    all_nodes = (volume_prof.get("anchors_above", []) or []) + \
                (volume_prof.get("anchors_below", []) or [])
    is_bullish = opinion == "BULLISH"

    # Derived states (inline — decoupled from regime_states)
    trend = float(market_reg.get("trend_intensity", 0.0))
    cvd = float(sentiment.get("cvd_intensity_ratio", 0.0))
    vol_exp = float(price_dyn.get("volatility_expansion_index", 1.0))
    squeeze = float(market_reg.get("squeeze_factor", 1.0))
    poc_dist = float(metrics.get("structural_anchors", {}).get("poc_dist_atr", 0.0))

    is_trend_strong = abs(trend) > regime_config.trend_intensity_strong
    has_cvd_momentum = abs(cvd) > regime_config.cvd_intensity_threshold
    is_chaos = vol_exp > regime_config.volatility_extreme_ratio
    is_squeezing = squeeze < regime_config.squeeze_threshold

    strategy = _infer_strategy(entry, current_price, atr, is_trend_strong,
                               has_cvd_momentum, is_chaos, is_squeezing,
                               opinion, trend, all_nodes, sentiment)

    d1 = (_score_anchor_quality(entry, sl, is_bullish, all_nodes, atr,
                                sentiment.get("liquidation_clusters"))
          + _score_betweenness(entry, sl, is_bullish, all_nodes, atr, is_trend_strong)
          + _score_entry_proximity(entry, current_price, atr, risk_config)
          + _score_entry_vacuum(entry, all_nodes, atr)
          + _score_multi_anchor(entry, sl, is_bullish, all_nodes, atr))

    d2 = (_score_flow_alignment(opinion, is_trend_strong, has_cvd_momentum,
                                trend, cvd)
          + _score_regime_fit(strategy, is_trend_strong, has_cvd_momentum,
                              is_chaos, is_squeezing, poc_dist,
                              risk_config)
          + _score_tp_proportional(tp, entry, is_bullish, is_chaos, is_squeezing,
                                   volume_prof, atr)
          + _score_polarity(opinion, trend, cvd, strategy))

    d3 = (_score_holding_ratio(proj_holding, entry, tp, atr,
                               market_reg.get("temporal_physics"))
          + _score_wait_hold(proj_waiting, proj_holding)
          + _score_squeeze_comp(is_chaos, is_squeezing, tp, entry,
                                is_bullish, volume_prof, atr)
          + _score_sentiment_risk(opinion, sentiment, regime_config, debate_history))

    penalty = _calc_debate_penalty(debate_history, entry, atr)
    score = d1 + d2 + d3 - penalty

    # TERMINAL veto cap: final score cannot exceed 80
    has_terminal = any(
        (entry.get("critic", {}).get("veto_level") or "").upper() == "TERMINAL"
        for entry in (debate_history or [])
        if isinstance(entry, dict)
    )
    if has_terminal:
        score = min(score, 80.0)

    return max(0.0, min(100.0, score))


# ── Strategy inference ────────────────────────────────────────

def _infer_strategy(entry: float, current_price: float, atr: float,
                    is_trend_strong: bool, has_cvd_momentum: bool,
                    is_chaos: bool, is_squeezing: bool,
                    opinion: str, trend: float,
                    all_nodes: list, sentiment: dict) -> str:
    """Infer entry strategy from coordinates and regime context.

    Returns one of: momentum_surge, shallow_pullback, dle_mean_reversion,
    hit_and_run, sweep_and_fade, liquidity_hunt.
    """
    if is_chaos:
        return "hit_and_run"
    if is_squeezing:
        return "liquidity_hunt"

    dist_atr = abs(entry - current_price) / atr if atr > 0 else 999.0

    if is_trend_strong and has_cvd_momentum:
        if dist_atr <= 0.3:
            return "momentum_surge"
        return "shallow_pullback"

    # Counter-trend detection: opinion vs trend sign
    trend_is_bullish = trend > 0
    trend_is_bearish = trend < 0
    is_counter_trend = ((opinion == "BULLISH" and trend_is_bearish) or
                        (opinion == "BEARISH" and trend_is_bullish))

    if is_counter_trend:
        # Check if entry is near a liquidation cluster
        liq = sentiment.get("liquidation_clusters", {}) or {}
        for cluster_list in liq.values():
            if not isinstance(cluster_list, list):
                continue
            for cluster in cluster_list:
                cp = float(cluster.get("price", 0))
                if cp > 0 and abs(entry - cp) / atr < 0.5:
                    return "sweep_and_fade"

    return "dle_mean_reversion"


# ── D1: Topographical Armor ───────────────────────────────────

def _score_anchor_quality(entry: float, sl: float, is_bullish: bool,
                          all_nodes: list, atr: float,
                          liq_clusters: dict | None) -> float:
    """Score 0–15. Anchor quality behind stop-loss."""
    protected_side_nodes = _nodes_on_protected_side(sl, is_bullish, all_nodes)
    if not protected_side_nodes:
        return 0.0

    anchor = protected_side_nodes[0]  # closest to sl
    strength = float(anchor.get("strength", 0))
    node_type = anchor.get("type", "")

    if node_type == "HVN":
        if strength >= _ANCHOR_STRONG:
            score = float(_ANCHOR_STRONG_LO + (strength - _ANCHOR_STRONG) /
                          (1.0 - _ANCHOR_STRONG) * (_ANCHOR_STRONG_HI - _ANCHOR_STRONG_LO))
        elif strength >= _ANCHOR_MODERATE:
            score = float(_ANCHOR_MODERATE_LO + (strength - _ANCHOR_MODERATE) /
                          (_ANCHOR_STRONG - _ANCHOR_MODERATE) * (_ANCHOR_MODERATE_HI - _ANCHOR_MODERATE_LO))
        else:
            score = float(_ANCHOR_WEAK_LO + strength / _ANCHOR_MODERATE *
                          (_ANCHOR_WEAK_HI - _ANCHOR_WEAK_LO))
    else:
        score = float(_ANCHOR_WEAK_LO + strength * (_ANCHOR_WEAK_HI - _ANCHOR_WEAK_LO))

    # Deduction: liquidation clusters between anchor and sl
    if liq_clusters:
        anchor_price = float(anchor.get("price", 0))
        lo = min(anchor_price, sl)
        hi = max(anchor_price, sl)
        for cluster_list in liq_clusters.values():
            if not isinstance(cluster_list, list):
                continue
            for cluster in cluster_list:
                cp = float(cluster.get("price", 0))
                if lo < cp < hi:
                    score -= _CLUSTER_PENALTY

    # Deduction: anchor too far from sl
    if abs(float(anchor.get("price", 0)) - sl) / atr > _ANCHOR_DISTANT_ATR:
        score -= 5.0

    return max(0.0, min(15.0, score))


def _score_betweenness(entry: float, sl: float, is_bullish: bool,
                       all_nodes: list, atr: float,
                       is_trend_strong: bool) -> float:
    """Score 0–10. Anchor strictly between entry and stop-loss."""
    protected_side_nodes = _nodes_on_protected_side(sl, is_bullish, all_nodes)
    if not protected_side_nodes:
        if is_trend_strong:
            return (_BETWEENNESS_DKS_LO + _BETWEENNESS_DKS_HI) / 2
        return 0.0

    anchor = protected_side_nodes[0]
    anchor_price = float(anchor.get("price", 0))
    gap_entry = abs(entry - anchor_price) / atr if atr > 0 else 0
    gap_sl = abs(anchor_price - sl) / atr if atr > 0 else 0

    if gap_entry >= _BETWEENNESS_GAP_ATR and gap_sl >= _BETWEENNESS_GAP_ATR:
        return _BETWEENNESS_PERFECT
    if gap_entry >= _BETWEENNESS_GAP_ATR or gap_sl >= _BETWEENNESS_GAP_ATR:
        return (_BETWEENNESS_ADJACENT_LO + _BETWEENNESS_ADJACENT_HI) / 2
    return _BETWEENNESS_ADJACENT_LO


def _score_entry_proximity(entry: float, current_price: float, atr: float,
                           risk_config) -> float:
    """Score 0–5. Entry distance from current price."""
    dist = abs(entry - current_price) / atr if atr > 0 else 999.0
    if dist <= _ENTRY_PROXIMITY_TIGHT:
        return _PROXIMITY_TIGHT
    if dist <= _ENTRY_PROXIMITY_LOOSE:
        return (_PROXIMITY_OK_LO + _PROXIMITY_OK_HI) / 2
    if dist <= risk_config.max_entry_distance_atr:
        return (_PROXIMITY_LOOSE_LO + _PROXIMITY_LOOSE_HI) / 2
    return 0.0


def _score_entry_vacuum(entry: float, all_nodes: list,
                        atr: float) -> float:
    """Score 0–5. Entry quality — on HVN vs LVN vs vacuum."""
    if not all_nodes:
        return 0.0

    closest = min(all_nodes, key=lambda n: abs(float(n.get("price", 0)) - entry))
    closest_dist = abs(float(closest.get("price", 0)) - entry) / atr if atr > 0 else 999.0

    if closest.get("type") == "HVN" and closest_dist < 0.3:
        return _VACUUM_HVN
    if closest.get("type") == "LVN":
        return (_VACUUM_LVN_LO + _VACUUM_LVN_HI) / 2
    if closest_dist < 1.0:
        return (_VACUUM_NEAR_HVN_LO + _VACUUM_NEAR_HVN_HI) / 2
    return 0.0


def _score_multi_anchor(entry: float, sl: float, is_bullish: bool,
                        all_nodes: list, atr: float) -> float:
    """Score 0–5. Second anchor quality on protected side."""
    protected = _nodes_on_protected_side(sl, is_bullish, all_nodes)
    if len(protected) < 2:
        return 0.0

    second = protected[1]
    strength = float(second.get("strength", 0))
    distance = abs(float(second.get("price", 0)) - sl) / atr if atr > 0 else 999.0

    if distance > _MULTI_FAR_ATR:
        return (_MULTI_WEAK_LO + _MULTI_WEAK_HI) / 2
    if strength >= _ANCHOR_MODERATE:
        return _MULTI_STRONG
    return (_MULTI_WEAK_LO + _MULTI_WEAK_HI) / 2


# ── D2: Regime & Gravity ─────────────────────────────────────

def _score_flow_alignment(opinion: str, is_trend_strong: bool,
                          has_cvd_momentum: bool, trend: float, cvd: float) -> float:
    """Score 0–10. Trend and CVD alignment with trade direction."""
    is_bullish = opinion == "BULLISH"
    trend_aligned = (is_bullish and trend > 0) or (not is_bullish and trend < 0)
    cvd_aligned = (is_bullish and cvd > 0) or (not is_bullish and cvd < 0)

    if is_trend_strong and has_cvd_momentum and trend_aligned and cvd_aligned:
        return _FLOW_BOTH_STRONG
    if is_trend_strong or has_cvd_momentum:
        if trend_aligned or cvd_aligned:
            return (_FLOW_ONE_STRONG_LO + _FLOW_ONE_STRONG_HI) / 2
        return 0.0
    return (_FLOW_NEUTRAL_LO + _FLOW_NEUTRAL_HI) / 2


def _score_regime_fit(strategy: str, is_trend_strong: bool,
                      has_cvd_momentum: bool, is_chaos: bool,
                      is_squeezing: bool, poc_dist: float,
                      risk_config) -> float:
    """Score 0–10. Strategy fit to current regime."""
    canonical = ("momentum_surge", "shallow_pullback")
    defensible = ("dle_mean_reversion", "sweep_and_fade", "liquidity_hunt")
    chaos_ok = ("hit_and_run",)

    if strategy in canonical and is_trend_strong and has_cvd_momentum:
        score = _REGIME_CANONICAL
    elif strategy in chaos_ok and is_chaos:
        score = _REGIME_CANONICAL
    elif strategy in defensible:
        if is_trend_strong:
            score = (_REGIME_DEFENSIBLE_LO + _REGIME_DEFENSIBLE_HI) / 2
        else:
            score = _REGIME_CANONICAL  # DLE in ranging → canonical
    elif strategy in canonical and not is_trend_strong:
        score = (_REGIME_MISMATCH_LO + _REGIME_MISMATCH_HI) / 2
    else:
        score = (_REGIME_DEFENSIBLE_LO + _REGIME_DEFENSIBLE_HI) / 2

    # Gravity cap
    if abs(poc_dist) > risk_config.poc_gravity_atr_distance and not is_trend_strong:
        score = min(score, _GRAVITY_CAP_MAX)

    return score


def _score_tp_proportional(tp: float, entry: float, is_bullish: bool,
                           is_chaos: bool, is_squeezing: bool,
                           volume_prof: dict, atr: float) -> float:
    """Score 0–5. Take-profit distance reasonableness."""
    tp_dist_atr = abs(tp - entry) / atr if atr > 0 else 999.0

    if is_chaos or is_squeezing:
        # First structural boundary
        boundary = volume_prof.get("vah" if is_bullish else "val", 0)
        if boundary and boundary > 0 and abs(tp - entry) <= abs(boundary - entry) * 1.1:
            return _TP_PROPORTIONAL_FIRST_BOUNDARY
        return (_SQUEEZE_LOOSE_LO + _SQUEEZE_LOOSE_HI) / 2

    if 1.0 <= tp_dist_atr <= 3.0:
        return (_TP_PROPORTIONAL_NORMAL_LO + _TP_PROPORTIONAL_NORMAL_HI) / 2
    return (_TP_PROPORTIONAL_EXCESSIVE_LO + _TP_PROPORTIONAL_EXCESSIVE_HI) / 2


def _score_polarity(opinion: str, trend: float, cvd: float,
                    strategy: str) -> float:
    """Score 0–5. Directional consistency across signals."""
    is_bullish = opinion == "BULLISH"
    bullish_strategies = ("momentum_surge", "shallow_pullback")
    bearish_strategies = ("sweep_and_fade",)  # counter-trend = opposite direction

    consistent = 0
    if (is_bullish and trend > 0) or (not is_bullish and trend < 0):
        consistent += 1
    if (is_bullish and cvd > 0) or (not is_bullish and cvd < 0):
        consistent += 1
    # Strategy direction
    if strategy in bullish_strategies:
        if is_bullish:
            consistent += 1
    elif strategy in bearish_strategies:
        if not is_bullish:
            consistent += 1
    else:
        consistent += 1  # neutral strategies compatible with any direction

    if consistent == 3:
        return _POLARITY_ALL
    if consistent == 2:
        return (_POLARITY_MINOR_LO + _POLARITY_MINOR_HI) / 2
    if consistent == 1:
        return (_POLARITY_MINOR_LO + _POLARITY_MAJOR) / 2
    return _POLARITY_MAJOR


# ── D3: Temporal & Sentiment ─────────────────────────────────

def _score_holding_ratio(proj_holding: float, entry: float, tp: float,
                         atr: float, temporal_physics: dict | None) -> float:
    """Score 0–10. Projected holding vs expected travel time."""
    if not temporal_physics:
        return 0.0
    unit_hours = float(temporal_physics.get("unit_atr_holding_hours", 0) or 0)
    if unit_hours <= 0:
        return 0.0

    expected = (abs(entry - tp) / atr) * unit_hours if atr > 0 else 0.0
    if expected <= 0:
        return 0.0
    ratio = proj_holding / expected

    if _HOLDING_RATIO_IDEAL_LO <= ratio <= _HOLDING_RATIO_IDEAL_HI:
        return (_HOLDING_IDEAL_LO + _HOLDING_IDEAL_HI) / 2
    if 0.5 <= ratio <= 2.0:
        return (_HOLDING_OK_LO + _HOLDING_OK_HI) / 2
    return (_HOLDING_BAD_LO + _HOLDING_BAD_HI) / 2


def _score_wait_hold(proj_waiting: float, proj_holding: float) -> float:
    """Score 0–8. Wait-to-hold ratio."""
    if proj_holding <= 0:
        return 0.0
    ratio = proj_waiting / proj_holding
    if ratio <= _WAIT_HOLD_TIGHT:
        return _WAIT_TIGHT
    if ratio <= _WAIT_HOLD_OK:
        return (_WAIT_OK_LO + _WAIT_OK_HI) / 2
    if ratio <= _WAIT_HOLD_MAX:
        return (_WAIT_LOOSE_LO + _WAIT_LOOSE_HI) / 2
    return (_WAIT_LONG_LO + _WAIT_LONG_HI) / 2


def _score_squeeze_comp(is_chaos: bool, is_squeezing: bool, tp: float,
                        entry: float, is_bullish: bool, volume_prof: dict,
                        atr: float) -> float:
    """Score 0–5. Squeeze/chaos take-profit compression."""
    if not is_chaos and not is_squeezing:
        return 0.0
    boundary = volume_prof.get("vah" if is_bullish else "val", 0)
    if boundary and boundary > 0 and abs(tp - entry) <= abs(boundary - entry) * 1.1:
        return _SQUEEZE_TIGHT
    return (_SQUEEZE_LOOSE_LO + _SQUEEZE_LOOSE_HI) / 2


def _score_sentiment_risk(opinion: str, sentiment: dict,
                          regime_config, debate_history: list | None) -> float:
    """Score 0–7. Retail positioning and funding risk."""
    is_bullish = opinion == "BULLISH"
    ls = float(sentiment.get("ls_ratio_micro", 1.0))
    funding = float(sentiment.get("funding_rate", 0.0))

    long_imbalance = ls > regime_config.long_short_imbalance_ratio
    short_imbalance = ls < regime_config.short_heavy_imbalance_ratio

    # SQUEEZE HARDENING check
    if debate_history:
        for entry in debate_history:
            critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
            for inv in (critic.get("invalidations", []) or []):
                tag = str(inv).split(" - ")[0].strip() if " - " in str(inv) else str(inv)
                if tag in ("[RETAIL_LONG_SQUEEZE]", "[RETAIL_SHORT_SQUEEZE]"):
                    return _SENTIMENT_SCORE_BALANCED

    retail_extreme = long_imbalance or short_imbalance
    retail_against = (is_bullish and long_imbalance) or (not is_bullish and short_imbalance)
    funding_extreme = abs(funding) > regime_config.funding_extreme_threshold
    funding_against = (is_bullish and funding > regime_config.funding_extreme_threshold) or \
                      (not is_bullish and funding < -regime_config.funding_extreme_threshold)

    if not retail_extreme:
        score = _SENTIMENT_SCORE_BALANCED
    elif retail_against:
        score = (_SENTIMENT_SCORE_AGAINST_LO + _SENTIMENT_SCORE_AGAINST_HI) / 2
    else:
        score = (_SENTIMENT_SCORE_ALIGNED_LO + _SENTIMENT_SCORE_ALIGNED_HI) / 2

    if funding_against:
        score -= _FUNDING_AGAINST_PENALTY

    return max(0.0, min(_SENTIMENT_SCORE_BALANCED, score))


# ── Penalty ───────────────────────────────────────────────────

def _calc_debate_penalty(debate_history: list | None,
                         current_entry: float,
                         atr: float) -> float:
    """Calculate debate penalty from round history."""
    if not debate_history:
        return 0.0

    has_terminal = False
    constructive_count = 0
    has_pass_after_constructive = False
    last_constructive_entry = None

    for entry in debate_history:
        critic = entry.get("critic", {}) if isinstance(entry, dict) else {}
        veto = (critic.get("veto_level") or "").upper()
        if veto == "TERMINAL":
            has_terminal = True
        elif veto == "CONSTRUCTIVE":
            constructive_count += 1
            plan = entry.get("plan", {}) if isinstance(entry, dict) else {}
            tp = plan.get("tactical_parameters", {})
            last_constructive_entry = float(tp.get("entry", 0) or 0) if isinstance(tp, dict) else None
        elif veto in ("PASS", "WEAK"):
            if constructive_count > 0:
                has_pass_after_constructive = True

    if has_terminal:
        # Paradigm shift: entry moved > 1 ATR or no last_constructive_entry to compare
        if last_constructive_entry is None:
            penalty = _DEBATE_TERMINAL_PARADIGM
        elif abs(current_entry - last_constructive_entry) > atr:
            penalty = _DEBATE_TERMINAL_PARADIGM
        else:
            penalty = _DEBATE_TERMINAL_COSMETIC
        return penalty

    if constructive_count >= 2 and not has_pass_after_constructive:
        return (_DEBATE_CONSTRUCTIVE_STALE_MIN + _DEBATE_CONSTRUCTIVE_STALE_MAX) / 2

    return 0.0


# ── Helpers ───────────────────────────────────────────────────

def _nodes_on_protected_side(sl: float, is_bullish: bool,
                              all_nodes: list) -> list:
    """Return nodes on the protected side of sl, sorted by distance to sl."""
    filtered = []
    for node in all_nodes:
        price = float(node.get("price", 0))
        if (is_bullish and price < sl) or (not is_bullish and price > sl):
            filtered.append((abs(price - sl), node))
    filtered.sort(key=lambda x: x[0])
    return [n for _, n in filtered]
