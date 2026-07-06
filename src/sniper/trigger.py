"""
Singularity Sniper Trigger — Signal Stack Architecture.

Replaces the old binary-trigger model with a continuous multi-signal confluence
engine. 14 signal types across 5 categories are detected per pulse, scored on
a 0–1 continuum, stacked directionally, and only fire an AI session when the
confluence score exceeds a regime-adaptive threshold.

See docs/trigger-design-20260625.md for the full design specification.
"""

import math
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List

from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class SignalCategory(str, Enum):
    FLOW = "FLOW"
    ENERGY = "ENERGY"
    STRUCTURAL = "STRUCTURAL"
    POSITIONING = "POSITIONING"
    CROSS_SYMBOL = "CROSS_SYMBOL"


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SignalCard:
    """A single detected market signal with continuous 0–1 scoring."""
    signal_id: str
    category: SignalCategory
    sub_type: str
    direction: Direction
    strength: float                         # 0.0–1.0
    confidence: float                       # 0.0–1.0, per-signal-type reliability weight
    urgency: float                          # 0.0–1.0, time-sensitivity
    timestamp: datetime
    decay_half_life_minutes: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    regime_compatibility: float = 1.0

    @property
    def weighted_score(self) -> float:
        """Effective score used in confluence stacking."""
        result = self.strength * self.confidence
        return 0.0 if math.isnan(result) or math.isinf(result) else result

    def decayed_strength(self, now: datetime) -> float:
        """Strength after applying temporal decay (half-life formula)."""
        elapsed = (now - self.timestamp).total_seconds() / 60.0
        if elapsed <= 0:
            return self.strength
        return self.strength * (0.5 ** (elapsed / max(self.decay_half_life_minutes, 1.0)))

@dataclass
class TriggerResult:
    """Output of trigger evaluation — replaces old (bool, str, str) tuple."""
    triggered: bool
    confluence_score: float                 # 0.0–1.0
    confluence_direction: Direction
    signals: List[SignalCard]               # all signals (including decayed survivors)
    active_signals: List[SignalCard]        # fresh signals that contributed to trigger
    gate_result: str                        # "PASS" | "WEAK_PASS" | "FAIL"
    gate_reason: str
    situation_brief: Optional[Dict[str, Any]]  # None if not triggered
    cooldown_minutes: float


@dataclass
class SignalMemory:
    """Tracks signals across pulses for decay and persistence."""
    active_signals: Dict[str, SignalCard] = field(default_factory=dict)

    def ingest(self, new_signals: List[SignalCard], now: datetime) -> List[SignalCard]:
        """Add new signals, decay existing ones, purge expired (strength < 0.05)."""
        decayed = []
        expired_keys = []
        for sid, card in self.active_signals.items():
            d_strength = card.decayed_strength(now)
            if d_strength > 0.05:
                card.strength = d_strength
                decayed.append(card)
            else:
                expired_keys.append(sid)

        for key in expired_keys:
            del self.active_signals[key]

        # Merge new signals (replace existing with same sub_type)
        for ns in new_signals:
            key = ns.sub_type
            self.active_signals[key] = ns

        # Return alive signals: fresh signals take priority over decayed survivors
        # (same sub_type in both → keep the fresh one, discard the stale one)
        fresh_keys = {ns.sub_type for ns in new_signals}
        return new_signals + [d for d in decayed if d.sub_type not in fresh_keys]


# ═══════════════════════════════════════════════════════════════════════════
# Confluence Engine
# ═══════════════════════════════════════════════════════════════════════════

class ConfluenceEngine:
    """Evaluates a stack of SignalCards and produces a confluence score + trigger decision."""

    def __init__(self, config: dict):
        # config is the signal_stack sub-dict
        self.base_threshold = config.get('trigger_threshold', 0.35)
        self.emergency_threshold = config.get('emergency_threshold', 0.85)
        self.regime_modifiers = config.get('regime_modifiers', {
            'trending': 0.85, 'ranging': 1.0, 'squeeze': 0.75, 'chaos': 1.50,
        })
        self.signal_weights = config.get('weights', {})
        self.min_strength_for_stack = 0.15

    def _directional_score(self, signals: List[SignalCard], direction: Direction) -> float:
        """1 - ∏(1 - s.weighted_score) for all signals matching direction."""
        matching = [s for s in signals
                    if s.direction == direction and s.strength >= self.min_strength_for_stack]
        if not matching:
            return 0.0
        product = 1.0
        for s in matching:
            product *= (1.0 - s.weighted_score)
        return 1.0 - product

    def _compute_confluence(self, signals: List[SignalCard]) -> Tuple[float, Direction]:
        """Returns (confluence_score, dominant_direction)."""
        bullish_score = self._directional_score(signals, Direction.BULLISH)
        bearish_score = self._directional_score(signals, Direction.BEARISH)

        noise_factor = 1.0 - (bullish_score * bearish_score)

        if bullish_score >= bearish_score:
            dominant = Direction.BULLISH
            raw_score = bullish_score
        else:
            dominant = Direction.BEARISH
            raw_score = bearish_score

        confluence_score = raw_score * noise_factor
        if math.isnan(confluence_score):
            logger.warning("NaN confluence — returning 0.0")
            return 0.0, Direction.NEUTRAL
        return confluence_score, dominant

    def evaluate(self, signals: List[SignalCard], regime: str,
                 is_cooldown_active: bool = False) -> Tuple[float, Direction, bool]:
        """
        Returns (confluence_score, dominant_direction, should_trigger).

        Considers: directional stacking, noise cancellation, regime modifier,
        emergency override, and cooldown.
        """
        confluence_score, dominant_direction = self._compute_confluence(signals)

        modifier = self.regime_modifiers.get(regime, 1.0)
        effective_threshold = self.base_threshold * modifier

        # Emergency override: fire if any single fresh signal exceeds emergency threshold
        emergency = any(
            s.strength >= self.emergency_threshold and s.direction != Direction.NEUTRAL
            for s in signals
        )

        should_trigger = emergency or (confluence_score >= effective_threshold)

        # During cooldown, only fire on emergency override or stacked break
        # (stacked break handled by caller via cooldown_break logic)
        if is_cooldown_active and not emergency:
            should_trigger = False

        return confluence_score, dominant_direction, should_trigger


# ═══════════════════════════════════════════════════════════════════════════
# SniperTrigger — Main Class
# ═══════════════════════════════════════════════════════════════════════════

class SniperTrigger:
    """
    Signal Stack trigger engine.

    Replaces the old binary-trigger model. Every 2-minute pulse, detects up to
    14 signal types, stacks them directionally via ConfluenceEngine, and fires
    an AI session only when confluence exceeds a regime-adaptive threshold.
    """

    # Cross-symbol correlation matrix: leader → {follower: coefficient}.
    # Only leaders listed as keys can propagate to followers.  Currently empty
    # (BTC and XAUT are independent); add entries when introducing ETH/SOL.
    #
    # Usage — when a leader symbol fires (WAKE), the daemon pushes a leader_sync
    # signal card to each follower listed under that leader.  The boost strength
    # is capped at 0.10 and only nudges a follower that is already close to its
    # own trigger threshold.  A single leader_sync card cannot cause a trigger on
    # its own.
    #
    # Calibration — effective correlation range is 0.50–0.80 (cap flattens
    # everything above 0.80).  For crypto majors that track BTC closely
    # (ETH, SOL), 0.70 is a good starting point.  For weaker relationships,
    # 0.50–0.60 gives a barely-felt nudge.  Tune based on backtest results.
    #
    # Example with ETH + SOL tracking BTC:
    #   CROSS_CORRELATIONS = {
    #       'BTCUSDT': {
    #           'ETHUSDT': 0.70,
    #           'SOLUSDT': 0.70,
    #       },
    #   }
    CROSS_CORRELATIONS: Dict[str, Dict[str, float]] = {}

    def __init__(self, strategy_cfg: Optional[dict] = None, global_cfg: Optional[dict] = None, symbol: Optional[str] = None):
        self.last_trigger_time: Optional[datetime] = None
        self.last_trigger_score: Optional[float] = None
        self._last_trigger_type: Optional[str] = None  # TRADED | NEUTRAL | OBSERVE_ONLY | ACTIVE_POSITION
        self.cooldown_active: bool = False
        self.symbol: Optional[str] = symbol

        # Config loading
        from src.utils.pipeline_utils import load_combined_config, load_global_config
        self.strat_cfg = strategy_cfg if strategy_cfg is not None else load_combined_config()
        self.global_cfg = global_cfg if global_cfg is not None else load_global_config()
        self.regime_cfg = self.strat_cfg['regime_parameters']
        self.sniper_cfg = self.global_cfg['sniper']

        # Default cooldown (used as fallback; adaptive cooldown is primary)
        micro_interval = self.strat_cfg['analysis_window']['micro_context']['time_interval']
        base_cooldown = self._parse_interval_to_minutes(micro_interval)
        self.cooldown_minutes = base_cooldown * self.sniper_cfg['signal_stack']['cooldown']['base_multiplier']

        # Confluence engine (receives signal_stack sub-config only)
        self.engine = ConfluenceEngine(self.sniper_cfg.get('signal_stack', {}))

        # Signal memory for inter-pulse decay
        self.memory = SignalMemory()

        # State locks for structural/sentiment patterns (ported from old trigger)
        self.state_locks: Dict[str, datetime] = {}

        # Signal confidence weights (convenience accessor)
        self.signal_weights = self.sniper_cfg.get('signal_stack', {}).get('weights', {})

        # Ordered signal detection registry
        self._signal_detectors = [
            # FLOW (fastest, most direct)
            self._detect_cvd_momentum,
            self._detect_cvd_divergence,
            self._detect_cvd_absorption,
            self._detect_taker_imbalance,
            # ENERGY
            self._detect_volatility_surge,
            self._detect_squeeze,
            # STRUCTURAL
            self._detect_boundary_test,
            self._detect_poc_gravity,
            self._detect_liquidation_hunt,
            self._detect_trend_pullback,
            # POSITIONING
            self._detect_retail_extreme,
            self._detect_oi_divergence,
            self._detect_oi_surge,
        ]

        logger.info(
            f"Signal Stack active | base={self.engine.base_threshold} | "
            f"emergency={self.engine.emergency_threshold} | "
            f"cooldown={self.cooldown_minutes}m | "
            f"detectors={len(self._signal_detectors)}"
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _parse_interval_to_minutes(self, interval_str: str) -> float:
        """Parse a Binance interval string ('15m', '1h', '1d') into float minutes."""
        val = int(interval_str[:-1])
        unit = interval_str[-1]
        if unit == 'h':
            return val * 60.0
        if unit == 'd':
            return val * 1440.0
        if unit == 'M':
            return val * 1440.0 * 30.0  # approximate month
        return float(val)

    def _check_state_lock(self, lock_key: str, now: datetime) -> bool:
        """Returns True if permitted to trigger, False if muted by state lock."""
        cooldown_hours = self.sniper_cfg['muting']['state_lockout_hours']
        if lock_key in self.state_locks:
            elapsed_hours = (now - self.state_locks[lock_key]).total_seconds() / 3600.0
            if elapsed_hours < cooldown_hours:
                return False
        self.state_locks[lock_key] = now
        return True

    # ── Regime Detection ─────────────────────────────────────────────────

    def _determine_regime(self, curr: Dict[str, Any]) -> str:
        """Classify current market regime for threshold modulation."""
        pd = curr.get('price_dynamics', {})
        mr = curr.get('market_regime', {})
        vii = pd.get('volatility_intensity_index', 0)
        sf = mr.get('squeeze_factor', 1.0)
        trend = abs(mr.get('trend_intensity', 0))
        trend_strong = self.regime_cfg['trend']['trend_intensity_strong']
        squeeze_threshold = self.regime_cfg['volatility']['squeeze_threshold']
        extreme_ratio = self.regime_cfg['volatility']['volatility_extreme_ratio']

        if vii > extreme_ratio:
            return 'chaos'
        if sf < squeeze_threshold:
            return 'squeeze'
        if trend > trend_strong:
            return 'trending'
        return 'ranging'

    # ── Adaptive Cooldown ────────────────────────────────────────────────

    def _check_adaptive_cooldown(self, now: datetime, regime: str) -> Tuple[bool, str]:
        """Returns (is_cooldown_active, reason_string)."""
        if not self.last_trigger_time:
            return False, ""

        cooldown_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {})
        if not cooldown_cfg:
            # No adaptive cooldown configured — fallback to fixed cooldown
            elapsed = (now - self.last_trigger_time).total_seconds() / 60.0
            if elapsed < self.cooldown_minutes:
                return True, f"GLOBAL_COOLDOWN ({elapsed:.1f}m/{self.cooldown_minutes}m)"
            return False, ""

        regime_minutes = cooldown_cfg.get('regime_base_minutes', {})
        cooldown_mins = regime_minutes.get(regime, self.cooldown_minutes)

        # Outcome-aware: NEUTRAL/OBSERVE_ONLY get shortened cooldown (no capital deployed)
        if self._last_trigger_type in ("NEUTRAL", "OBSERVE_ONLY"):
            neutral_mult = cooldown_cfg.get('neutral_multiplier', 1.0)
            cooldown_mins = cooldown_mins * neutral_mult

        elapsed = (now - self.last_trigger_time).total_seconds() / 60.0

        # Enforce minimum gap after any cooldown break
        min_gap = cooldown_cfg.get('break_min_gap_minutes', 10)
        if elapsed < min_gap:
            return True, f"MIN_GAP ({elapsed:.1f}m/{min_gap}m)"

        if elapsed < cooldown_mins:
            return True, f"COOLDOWN_{regime.upper()} ({elapsed:.1f}m/{cooldown_mins}m)"

        return False, ""

    def _get_regime_cooldown(self, regime: str) -> float:
        """Return the cooldown that will be applied after a trigger in this regime."""
        cooldown_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {})
        regime_minutes = cooldown_cfg.get('regime_base_minutes', {})
        return regime_minutes.get(regime, self.cooldown_minutes)

    def _check_cooldown_break(self, fresh_signals: List[SignalCard],
                              regime: str) -> bool:
        """Check if cooldown should break due to stacked signals or strength ratio."""
        cooldown_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {})

        # Break if 3+ fresh signals stack in same direction
        stacked_count = cooldown_cfg.get('stacked_break_count', 3)
        dir_counts: Dict[Direction, int] = {}
        for s in fresh_signals:
            if s.direction != Direction.NEUTRAL and s.strength >= 0.15:
                dir_counts[s.direction] = dir_counts.get(s.direction, 0) + 1
        for direction, count in dir_counts.items():
            if count >= stacked_count:
                logger.info(
                    "[%s] cooldown break: stacked | dir=%s count=%d threshold=%d",
                    self.symbol, direction.value, count, stacked_count,
                )
                return True

        # Break if any fresh signal exceeds strength ratio vs last trigger
        if self.last_trigger_score is not None:
            break_ratio = cooldown_cfg.get('break_on_strength_ratio', 1.8)
            ratio_threshold = self.last_trigger_score * break_ratio
            for s in fresh_signals:
                if s.weighted_score >= ratio_threshold:
                    logger.info(
                        "[%s] cooldown break: strength_ratio | signal=%s "
                        "weighted=%.3f threshold=%.3f (last_score=%.3f × %.1f)",
                        self.symbol, s.sub_type, s.weighted_score,
                        ratio_threshold, self.last_trigger_score, break_ratio,
                    )
                    return True

        return False

    # ── Pre-AI Gate ──────────────────────────────────────────────────────

    def _run_pre_ai_gate(self, curr: Dict[str, Any],
                         signals: List[SignalCard],
                         direction: Direction,
                         regime: str) -> Tuple[str, str]:
        """Deterministic pre-check before spending AI tokens. Returns (result, reason)."""
        gate_cfg = self.sniper_cfg.get('signal_stack', {}).get('gate', {})
        if not gate_cfg.get('enabled', True):
            return "PASS", "gate disabled"

        checks = gate_cfg.get('checks', {})
        atr = curr['price_dynamics'].get('atr_macro', 0)
        price = curr['price_dynamics'].get('current_price', 0)
        topo = curr.get('volume_profile', {})

        # 1. Entry feasibility
        if checks.get('entry_feasibility', True):
            max_dist = gate_cfg.get('max_price_to_structure_atr', 1.0)
            if direction == Direction.BULLISH:
                # Need structure BELOW for entry
                anchors = topo.get('anchors_below', [])
            else:
                anchors = topo.get('anchors_above', [])
            nearest_hvn = next((a for a in (anchors or []) if a.get('type') == 'HVN'), None)
            if nearest_hvn and atr > 0:
                dist = abs(price - nearest_hvn['price']) / atr
                if dist > max_dist:
                    return "FAIL", f"ENTRY_FEASIBILITY: nearest structure at {dist:.1f} ATR > {max_dist}"

        # 2. Directional sanity
        if checks.get('directional_sanity', True):
            trend = curr['market_regime'].get('trend_intensity', 0)
            trend_strong = self.regime_cfg['trend']['trend_intensity_strong']
            cvd = curr['sentiment_signals'].get('cvd_intensity_ratio', 0)
            cvd_threshold = self.regime_cfg['micro_sentiment'].get('cvd_intensity_threshold', 0.1)
            # Counter-trend without structural anchor → suspect
            if direction == Direction.BULLISH and trend < -trend_strong:
                if abs(cvd) < cvd_threshold:
                    return "FAIL", "DIRECTIONAL_SANITY: BULLISH against strong bearish trend without CVD confirmation"
            if direction == Direction.BEARISH and trend > trend_strong:
                if abs(cvd) < cvd_threshold:
                    return "FAIL", "DIRECTIONAL_SANITY: BEARISH against strong bullish trend without CVD confirmation"

        # 3. Chaos survival
        if checks.get('chaos_survival', True) and regime == 'chaos':
            # Directional momentum signals in chaos are prohibited
            momentum_signals = [s for s in signals
                              if s.sub_type in ('cvd_momentum', 'volatility_surge')
                              and s.direction == direction]
            if momentum_signals and not any(
                s.sub_type in ('squeeze', 'cvd_absorption') for s in signals
            ):
                return "FAIL", "CHAOS_SURVIVAL: directional momentum prohibited in chaos regime"

        return "PASS", ""

    # ── Pre-Brief Builder ────────────────────────────────────────────────

    def _build_situation_brief(self, all_signals: List[SignalCard],
                         confluence_score: float,
                         direction: Direction,
                         regime: str,
                         gate_result: str) -> Dict[str, Any]:
        """Build the pre-brief JSON injected into the SessionAgent's observation."""
        active = [s for s in all_signals
                  if s.strength >= 0.15 and s.direction in (direction, Direction.NEUTRAL)]

        activated_by = []
        for s in sorted(all_signals, key=lambda x: x.weighted_score, reverse=True)[:5]:
            if s.direction != Direction.NEUTRAL or s.sub_type == 'squeeze':
                thesis = self._suggest_thesis(s.sub_type, s.direction)
                activated_by.append({
                    "signal": s.sub_type.upper(),
                    "direction": s.direction.value,
                    "strength": round(s.strength, 2),
                    "confidence": round(s.confidence, 2),
                    "key_evidence": self._format_evidence(s),
                    "suggested_thesis": thesis,
                })

        risk_caveats = self._build_risk_caveats(all_signals, direction, regime)

        suggested_entry = self._build_entry_suggestion(all_signals, direction, regime)

        return {
            "confluence_score": round(confluence_score, 2),
            "confluence_direction": direction.value,
            "stacked_signals_count": len(active),
            "regime_note": self._build_regime_note(direction, regime),
            "gate_result": gate_result,
            "activated_by": activated_by,
            "risk_caveats": risk_caveats,
            "suggested_entry_zone": suggested_entry,
        }

    def _suggest_thesis(self, sub_type: str, direction: Direction) -> str:
        theses = {
            'cvd_momentum': (
                "Bearish momentum building — seek short on pullback to nearest HVN"
                if direction == Direction.BEARISH else
                "Bullish momentum building — seek long on dip to nearest HVN"
            ),
            'cvd_divergence': (
                "Distribution detected — smart money selling into strength, prepare short"
                if direction == Direction.BEARISH else
                "Accumulation detected — smart money buying into weakness, prepare long"
            ),
            'cvd_absorption': (
                "Iceberg selling absorption — large player accumulating shorts, expect downside"
                if direction == Direction.BEARISH else
                "Iceberg buying absorption — large player accumulating longs, expect upside"
            ),
            'taker_imbalance': (
                "Aggressive selling pressure — follow the flow short"
                if direction == Direction.BEARISH else
                "Aggressive buying pressure — follow the flow long"
            ),
            'volatility_surge': (
                "Breakout energy with bearish flow — momentum short entry"
                if direction == Direction.BEARISH else
                "Breakout energy with bullish flow — momentum long entry"
            ),
            'squeeze': "Coiling spring — prepare for violent expansion, direction TBD on breakout",
            'boundary_test': (
                "Testing resistance — if rejection, fade short; if breakout with volume, follow"
                if direction == Direction.BULLISH else
                "Testing support — if rejection, fade long; if breakdown with volume, follow"
            ),
            'poc_gravity': "Mean-reversion gravity active — price pulled toward fair value (POC)",
            'liquidation_hunt': "Liquidity sweep in progress — enter after cluster is cleared",
            'trend_pullback': (
                "Trend pullback to structure — high-probability entry in trend direction (BEARISH)"
                if direction == Direction.BEARISH else
                "Trend pullback to structure — high-probability entry in trend direction (BULLISH)"
            ),
            'retail_extreme': (
                "Retail overcrowded long — squeeze fuel for downside cascade"
                if direction == Direction.BEARISH else
                "Retail overcrowded short — squeeze fuel for upside cascade"
            ),
            'oi_divergence': (
                "OI dropping while price rises — short-squeeze exhaustion, bearish reversal ahead"
                if direction == Direction.BEARISH else
                "OI rising while price drops — accumulation, bullish reversal ahead"
            ),
            'oi_surge': (
                "Fresh capital entering shorts — trend continuation fuel"
                if direction == Direction.BEARISH else
                "Fresh capital entering longs — trend continuation fuel"
            ),
        }
        return theses.get(sub_type, f"Signal detected — evaluate against market structure")

    def _format_evidence(self, s: SignalCard) -> str:
        """One-line summary of signal evidence for the pre-brief."""
        ev = s.evidence
        if s.sub_type == 'cvd_momentum':
            return f"CVD intensity {ev.get('cvd_intensity', 0.0):.3f}"
        if s.sub_type == 'cvd_divergence':
            return f"CVD delta {ev.get('cvd_delta', 0.0):.3f} vs price delta {ev.get('price_delta', 0.0):.1f}"
        if s.sub_type == 'cvd_absorption':
            return f"CVD {ev.get('cvd_intensity', 0.0):.3f} with flat price (delta {ev.get('price_delta', 0.0):.1f})"
        if s.sub_type == 'taker_imbalance':
            return f"CVD {ev.get('cvd_intensity', 0.0):.3f} (taker imbalance equivalent)"
        if s.sub_type == 'volatility_surge':
            return f"VII={ev.get('vii', 0.0):.2f}, VPR={ev.get('vpr', 0.0):.2f}"
        if s.sub_type == 'squeeze':
            return f"Squeeze factor {ev.get('squeeze_factor', 0.0):.2f}"
        if s.sub_type == 'boundary_test':
            return f"Distance to {ev.get('boundary', '?')}: {ev.get('dist_atr', 0.0):.2f} ATR"
        if s.sub_type == 'poc_gravity':
            return f"POC distance: {ev.get('poc_dist_atr', 0.0):.2f} ATR"
        if s.sub_type == 'liquidation_hunt':
            return f"Cluster at {ev.get('cluster_price', 0.0):.1f}, distance: {ev.get('dist_atr', 0.0):.2f} ATR"
        if s.sub_type == 'trend_pullback':
            return f"Trend={ev.get('trend_intensity', 0.0):.2f}, dist to structure={ev.get('dist_to_structure_atr', 0.0):.2f} ATR"
        if s.sub_type == 'retail_extreme':
            trigger = ev.get('trigger', '?')
            if trigger == 'ls_long':
                return f"LS ratio {ev.get('ls_ratio', 0.0):.2f} — retail heavily long"
            elif trigger == 'ls_short':
                return f"LS ratio {ev.get('ls_ratio', 0.0):.2f} — retail heavily short"
            elif trigger == 'funding':
                return f"Funding rate {ev.get('funding_rate', 0.0):.5f} — extreme"
        if s.sub_type == 'oi_divergence':
            return f"OI delta {ev.get('oi_delta', 0.0):.3f} vs price delta {ev.get('price_delta', 0.0):.1f}"
        if s.sub_type == 'oi_surge':
            return f"OI delta {ev.get('oi_delta', 0.0):.3f} aligned with price delta {ev.get('price_delta', 0.0):.1f}"
        return str(ev)[:120]

    def _build_risk_caveats(self, signals: List[SignalCard],
                            direction: Direction, regime: str) -> List[str]:
        caveats = []
        sub_types = {s.sub_type for s in signals}

        if 'retail_extreme' in sub_types:
            caveats.append(
                "Retail extreme can persist for hours — do not force entry without structural confirmation"
            )
        if 'cvd_momentum' in sub_types and 'cvd_absorption' not in sub_types:
            caveats.append(
                "CVD momentum is strong but watch for absorption — extreme CVD without price movement = reversal risk"
            )
        if 'trend_pullback' in sub_types:
            caveats.append(
                "Trend pullback is the highest-quality setup — prioritize structure-anchored entry"
            )
        if regime == 'chaos':
            caveats.append(
                "CHAOS regime active — use hit-and-run strategy, compress TP to first structural boundary"
            )
        if regime == 'squeeze':
            caveats.append(
                "Squeeze active — expect violent breakout, use wider stop or wait for direction confirmation"
            )
        if 'cvd_divergence' in sub_types and direction == Direction.BEARISH:
            caveats.append(
                "Distribution divergence — smart money may be selling into strength, size conservatively"
            )
        return caveats

    def _build_entry_suggestion(self, signals: List[SignalCard],
                                 direction: Direction, regime: str) -> Dict[str, Any]:
        max_dist = self.sniper_cfg.get('signal_stack', {}).get('gate', {}).get(
            'max_price_to_structure_atr', 1.0)
        suggestion = {
            "max_distance_atr": max_dist,
        }

        if any(s.sub_type == 'trend_pullback' for s in signals):
            suggestion["type"] = "trend_pullback_dle"
            suggestion["target_area"] = "nearest HVN in trend direction"
        elif any(s.sub_type == 'cvd_divergence' for s in signals):
            suggestion["type"] = "divergence_fade"
            suggestion["target_area"] = "proximal structural boundary"
        elif any(s.sub_type == 'squeeze' for s in signals):
            suggestion["type"] = "squeeze_breakout"
            suggestion["target_area"] = "beyond VAH/VAL on confirmed breakout direction"
        elif regime == 'chaos':
            suggestion["type"] = "hit_and_run"
            suggestion["target_area"] = "nearest liquidation cluster or VAH/VAL boundary"
        elif direction == Direction.BEARISH:
            suggestion["type"] = "shallow_pullback_dle"
            suggestion["target_area"] = "nearest HVN above current price"
        else:
            suggestion["type"] = "shallow_dip_dle"
            suggestion["target_area"] = "nearest HVN below current price"

        return suggestion

    def _build_regime_note(self, direction: Direction, regime: str) -> str:
        notes = {
            'trending': (
                f"IS_TREND_STRONG {direction.value} — momentum entries authorized, "
                f"Dynamic Kinetic Shield available, counter-trend prohibited"
            ),
            'ranging': (
                "Ranging regime — mean-reversion entries preferred, "
                "tighten TP to nearest structural boundary"
            ),
            'squeeze': (
                "Squeeze regime — coiling spring, prepare for breakout, "
                "direction TBD on expansion, use wider stops"
            ),
            'chaos': (
                "CHAOS regime — hit-and-run only, directional momentum PROHIBITED, "
                "survival priority, compress TP aggressively"
            ),
        }
        return notes.get(regime, f"Regime: {regime}")

    # ═══════════════════════════════════════════════════════════════════════
    # SIGNAL DETECTORS (13 direct + 1 cross-symbol = 14 total)
    # ═══════════════════════════════════════════════════════════════════════

    def _make_id(self, sub_type: str, now: datetime) -> str:
        return f"{sub_type}_{now.strftime('%Y%m%d_%H%M%S')}"

    # ── FLOW: CVD Momentum (#1) ────────────────────────────────────────

    def _detect_cvd_momentum(self, curr: Dict[str, Any],
                              prev: Optional[Dict[str, Any]],
                              now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        if abs(cvd) <= threshold:
            return None

        if prev:
            prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
            growth_ratio = self.sniper_cfg['probes']['cvd_growth_significance_ratio']
            if abs(cvd) < abs(prev_cvd) * growth_ratio:
                return None

        direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        strength = min(abs(cvd) / (threshold * 3), 1.0)
        confidence = self.signal_weights.get('cvd_momentum', 0.65)

        return SignalCard(
            signal_id=self._make_id('cvd_momentum', now),
            category=SignalCategory.FLOW,
            sub_type='cvd_momentum',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.5,
            timestamp=now,
            decay_half_life_minutes=15.0,
            evidence={'cvd_intensity': cvd, 'threshold': threshold},
        )

    # ── FLOW: CVD Divergence (#2) ──────────────────────────────────────

    def _detect_cvd_divergence(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        if not prev:
            return None
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
        cvd_delta = cvd - prev_cvd
        threshold = self.sniper_cfg['signal_stack']['thresholds']['cvd_divergence_tick_delta']
        if abs(cvd_delta) <= threshold:
            return None

        price_delta = (curr['price_dynamics']['current_price'] -
                       prev['price_dynamics']['current_price'])
        if not ((price_delta > 0 and cvd_delta < 0) or (price_delta < 0 and cvd_delta > 0)):
            return None

        direction = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
        strength = min(abs(cvd_delta) / (threshold * 3), 1.0)
        confidence = self.signal_weights.get('cvd_divergence', 0.70)

        return SignalCard(
            signal_id=self._make_id('cvd_divergence', now),
            category=SignalCategory.FLOW,
            sub_type='cvd_divergence',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.7,
            timestamp=now,
            decay_half_life_minutes=4.0,
            evidence={'cvd_delta': cvd_delta, 'price_delta': price_delta, 'threshold': threshold},
        )

    # ── FLOW: CVD Absorption (#3) ──────────────────────────────────────

    def _detect_cvd_absorption(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        extreme_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_extreme']
        if abs(cvd) <= extreme_threshold:
            return None
        if not prev:
            return None
        price_delta = abs(curr['price_dynamics']['current_price'] -
                          prev['price_dynamics']['current_price'])
        atr_micro = curr['price_dynamics'].get('atr_micro', 0)
        if atr_micro <= 0:
            return None
        if price_delta >= 0.3 * atr_micro:
            return None

        direction = Direction.BEARISH if cvd > 0 else Direction.BULLISH
        saturation_denom = max(extreme_threshold * 1.5, 0.15)
        strength = min((abs(cvd) - extreme_threshold) / saturation_denom, 1.0)
        confidence = self.signal_weights.get('cvd_absorption', 0.65)

        return SignalCard(
            signal_id=self._make_id('cvd_absorption', now),
            category=SignalCategory.FLOW,
            sub_type='cvd_absorption',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.6,
            timestamp=now,
            decay_half_life_minutes=10.0,
            evidence={'cvd_intensity': cvd, 'price_delta': price_delta},
        )

    # ── FLOW: Taker Imbalance (#4) ─────────────────────────────────────
    # Derived from cvd_intensity_ratio. Threshold configurable per symbol
    # via signal_stack.thresholds.taker_imbalance (default 0.20).

    def _detect_taker_imbalance(self, curr: Dict[str, Any],
                                 prev: Optional[Dict[str, Any]],
                                 now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        # |cvd| must exceed this threshold to fire (configurable per symbol via
        # signal_stack.thresholds.taker_imbalance; default 0.20).
        threshold = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {}).get('taker_imbalance', 0.20)
        if abs(cvd) <= threshold:
            return None

        direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        # Saturate denominator scales with threshold so calibration holds across symbols
        saturation_denom = max(threshold * 2, 0.40)
        strength = min((abs(cvd) - threshold) / saturation_denom, 1.0)
        confidence = self.signal_weights.get('taker_imbalance', 0.60)

        return SignalCard(
            signal_id=self._make_id('taker_imbalance', now),
            category=SignalCategory.FLOW,
            sub_type='taker_imbalance',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.6,
            timestamp=now,
            decay_half_life_minutes=4.0,
            evidence={'cvd_intensity': cvd},
        )

    # ── ENERGY: Volatility Surge (#5) ───────────────────────────────────

    def _detect_volatility_surge(self, curr: Dict[str, Any],
                                  prev: Optional[Dict[str, Any]],
                                  now: datetime) -> Optional[SignalCard]:
        vii = curr['price_dynamics']['volatility_intensity_index']
        vpr = curr['market_regime']['volume_participation_ratio']
        baseline = self.regime_cfg['volatility']['volatility_baseline_ratio']
        vol_threshold = self.regime_cfg['volume']['volume_participation_threshold']

        if not (vii > baseline and vpr > vol_threshold):
            return None

        if prev:
            prev_vii = prev['price_dynamics']['volatility_intensity_index']
            growth_ratio = self.sniper_cfg['probes'].get('volatility_growth_significance_ratio', 1.03)
            if vii <= prev_vii * growth_ratio:
                return None

        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        if abs(cvd) > 0.05:
            direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        elif abs(trend := curr['market_regime'].get('trend_intensity', 0)) > 0.05:
            direction = Direction.BULLISH if trend > 0 else Direction.BEARISH
        else:
            direction = Direction.NEUTRAL  # flat — no directional bias

        strength = min((vii - baseline) / (baseline * 2), 1.0)
        confidence = self.signal_weights.get('volatility_surge', 0.55)

        return SignalCard(
            signal_id=self._make_id('volatility_surge', now),
            category=SignalCategory.ENERGY,
            sub_type='volatility_surge',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.5,
            timestamp=now,
            decay_half_life_minutes=20.0,
            evidence={'vii': vii, 'vpr': vpr},
        )

    # ── ENERGY: Squeeze (#6) ─────────────────────────────────────────────

    def _detect_squeeze(self, curr: Dict[str, Any],
                         prev: Optional[Dict[str, Any]],
                         now: datetime) -> Optional[SignalCard]:
        sf = curr['market_regime']['squeeze_factor']
        threshold = (self.regime_cfg['volatility']['squeeze_threshold'] *
                     self.sniper_cfg['probes']['squeeze_trigger_multiplier'])
        if sf >= threshold:
            return None

        if prev:
            prev_sf = prev['market_regime']['squeeze_factor']
            if sf >= prev_sf * 0.98:
                return None

        strength = min((threshold - sf) / threshold, 1.0)
        confidence = self.signal_weights.get('squeeze', 0.75)

        return SignalCard(
            signal_id=self._make_id('squeeze', now),
            category=SignalCategory.ENERGY,
            sub_type='squeeze',
            direction=Direction.NEUTRAL,
            strength=strength,
            confidence=confidence,
            urgency=0.9,
            timestamp=now,
            decay_half_life_minutes=20.0,
            evidence={'squeeze_factor': sf, 'threshold': threshold},
        )

    # ── STRUCTURAL: Boundary Test (#7) ──────────────────────────────────

    def _detect_boundary_test(self, curr: Dict[str, Any],
                               prev: Optional[Dict[str, Any]],
                               now: datetime) -> Optional[SignalCard]:
        topo = curr['volume_profile']
        atr = curr['price_dynamics'].get('atr_macro', 0)
        if atr <= 0:
            return None
        price = curr['price_dynamics']['current_price']
        part = curr['market_regime']['volume_participation_ratio']

        dist_vh = abs(price - topo['vah']) / atr
        dist_val = abs(price - topo['val']) / atr
        threshold = self.sniper_cfg['proximity']['vah_val_atr']

        nearest_dist = min(dist_vh, dist_val)
        nearest = 'VAH' if dist_vh < dist_val else 'VAL'

        if nearest_dist >= threshold or part <= self.regime_cfg['volume']['min_volume_participation_ratio']:
            return None

        if prev:
            prev_price = prev['price_dynamics']['current_price']
            approaching_up = nearest == 'VAH' and price > prev_price
            approaching_down = nearest == 'VAL' and price < prev_price
            if not (approaching_up or approaching_down):
                return None

        if not self._check_state_lock(f"BOUNDARY_{nearest}", now):
            return None

        direction = Direction.BULLISH if nearest == 'VAH' else Direction.BEARISH
        strength = min(threshold / max(nearest_dist, 0.01) * 0.25, 1.0)
        confidence = self.signal_weights.get('boundary_test', 0.50)

        return SignalCard(
            signal_id=self._make_id('boundary_test', now),
            category=SignalCategory.STRUCTURAL,
            sub_type='boundary_test',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.4,
            timestamp=now,
            decay_half_life_minutes=10.0,
            evidence={'boundary': nearest, 'dist_atr': nearest_dist, 'threshold': threshold},
        )

    # ── STRUCTURAL: POC Gravity (#8) ────────────────────────────────────

    def _detect_poc_gravity(self, curr: Dict[str, Any],
                             prev: Optional[Dict[str, Any]],
                             now: datetime) -> Optional[SignalCard]:
        poc_dist = curr['structural_anchors'].get('poc_dist_atr', 0)
        threshold = self.sniper_cfg['proximity']['poc_atr']
        if abs(poc_dist) >= threshold:
            return None  # too far from POC — gravity not active

        if prev:
            prev_price = prev['price_dynamics']['current_price']
            price = curr['price_dynamics']['current_price']
            poc = curr['volume_profile']['poc']
            approaching = (price < poc and price > prev_price) or (price > poc and price < prev_price)
            if not approaching:
                return None

        if not self._check_state_lock("POC_MAGNET", now):
            return None

        direction = Direction.BULLISH if poc_dist < 0 else Direction.BEARISH
        strength = min(threshold / max(abs(poc_dist), 0.01) * 0.20, 1.0)
        confidence = self.signal_weights.get('poc_gravity', 0.55)

        return SignalCard(
            signal_id=self._make_id('poc_gravity', now),
            category=SignalCategory.STRUCTURAL,
            sub_type='poc_gravity',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.3,
            timestamp=now,
            decay_half_life_minutes=10.0,
            evidence={'poc_dist_atr': poc_dist, 'threshold': threshold},
        )

    # ── STRUCTURAL: Liquidation Hunt (#9) ────────────────────────────────

    def _detect_liquidation_hunt(self, curr: Dict[str, Any],
                                  prev: Optional[Dict[str, Any]],
                                  now: datetime) -> Optional[SignalCard]:
        liq_clusters = curr['sentiment_signals'].get('liquidation_clusters')
        if not liq_clusters or not isinstance(liq_clusters, dict):
            return None

        atr = curr['price_dynamics'].get('atr_macro', 0)
        if atr <= 0:
            return None
        price = curr['price_dynamics']['current_price']
        threshold = self.sniper_cfg['proximity']['liq_atr']

        # Check long liquidation clusters (price moving DOWN to sweep)
        for cluster in liq_clusters.get('long_liquidation', []):
            p = float(cluster['price'])
            dist_atr = abs(price - p) / atr
            if dist_atr < threshold:
                if prev:
                    prev_price = prev['price_dynamics']['current_price']
                    if price >= prev_price:
                        continue
                if self._check_state_lock(f"LONG_LIQ_{int(p/100)*100}", now):
                    strength = min(threshold / max(dist_atr, 0.01) * 0.15, 1.0)
                    return SignalCard(
                        signal_id=self._make_id('liquidation_hunt', now),
                        category=SignalCategory.STRUCTURAL,
                        sub_type='liquidation_hunt',
                        direction=Direction.BEARISH,
                        strength=strength,
                        confidence=self.signal_weights.get('liquidation_hunt', 0.60),
                        urgency=0.5,
                        timestamp=now,
                        decay_half_life_minutes=10.0,
                        evidence={'cluster_price': p, 'dist_atr': dist_atr, 'type': 'long'},
                    )

        # Check short liquidation clusters (price moving UP to squeeze)
        for cluster in liq_clusters.get('short_liquidation', []):
            p = float(cluster['price'])
            dist_atr = abs(price - p) / atr
            if dist_atr < threshold:
                if prev:
                    prev_price = prev['price_dynamics']['current_price']
                    if price <= prev_price:
                        continue
                if self._check_state_lock(f"SHORT_LIQ_{int(p/100)*100}", now):
                    strength = min(threshold / max(dist_atr, 0.01) * 0.15, 1.0)
                    return SignalCard(
                        signal_id=self._make_id('liquidation_hunt', now),
                        category=SignalCategory.STRUCTURAL,
                        sub_type='liquidation_hunt',
                        direction=Direction.BULLISH,
                        strength=strength,
                        confidence=self.signal_weights.get('liquidation_hunt', 0.60),
                        urgency=0.5,
                        timestamp=now,
                        decay_half_life_minutes=10.0,
                        evidence={'cluster_price': p, 'dist_atr': dist_atr, 'type': 'short'},
                    )

        return None

    # ── STRUCTURAL: Trend Pullback (#10) ─────────────────────────────────

    def _detect_trend_pullback(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        trend = curr['market_regime'].get('trend_intensity', 0)
        strong_threshold = self.regime_cfg['trend']['trend_intensity_strong']
        if abs(trend) <= strong_threshold:
            return None

        direction = Direction.BULLISH if trend > 0 else Direction.BEARISH
        price = curr['price_dynamics']['current_price']
        atr = curr['price_dynamics'].get('atr_macro', 0)
        if atr <= 0:
            return None
        vp = curr['volume_profile']
        max_dist = self.sniper_cfg.get('signal_stack', {}).get('gate', {}).get(
            'max_price_to_structure_atr', 1.0)

        if direction == Direction.BULLISH:
            target_price = vp.get('poc', price)
            for anchor in vp.get('anchors_below', []):
                if anchor.get('type') == 'HVN':
                    target_price = anchor['price']
                    break
            dist_atr = abs(price - target_price) / atr
            if price <= target_price:
                return None
        else:
            target_price = vp.get('poc', price)
            for anchor in vp.get('anchors_above', []):
                if anchor.get('type') == 'HVN':
                    target_price = anchor['price']
                    break
            dist_atr = abs(price - target_price) / atr
            if price >= target_price:
                return None

        if dist_atr > max_dist:
            return None

        strength = min(abs(trend) * (1.0 - dist_atr / max_dist), 1.0)
        confidence = self.signal_weights.get('trend_pullback', 0.75)

        return SignalCard(
            signal_id=self._make_id('trend_pullback', now),
            category=SignalCategory.STRUCTURAL,
            sub_type='trend_pullback',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.6,
            timestamp=now,
            decay_half_life_minutes=10.0,
            evidence={'trend_intensity': trend, 'dist_to_structure_atr': dist_atr},
        )

    # ── POSITIONING: Retail Extreme (#11) ───────────────────────────────

    def _detect_retail_extreme(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        ls = curr['sentiment_signals'].get('ls_ratio_micro', 1.0)
        funding = curr['sentiment_signals'].get('funding_rate', 0.0)
        cfg = self.regime_cfg['imbalance']

        direction = None
        strength = 0.0
        evidence: Dict[str, Any] = {}

        if ls > cfg['long_short_imbalance_ratio']:
            direction = Direction.BEARISH
            strength = min((ls - 1.0) / (cfg['long_short_imbalance_ratio'] * 2), 1.0)
            evidence = {'trigger': 'ls_long', 'ls_ratio': ls}
        elif ls < cfg['short_heavy_imbalance_ratio']:
            direction = Direction.BULLISH
            strength = min((1.0 - ls) / ((1.0 - cfg['short_heavy_imbalance_ratio']) * 2), 1.0)
            evidence = {'trigger': 'ls_short', 'ls_ratio': ls}

        funding_threshold = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        if abs(funding) > funding_threshold:
            f_direction = Direction.BEARISH if funding > 0 else Direction.BULLISH
            f_strength = min(abs(funding) / (funding_threshold * 4), 1.0)
            if direction is None or f_strength > strength:
                direction = f_direction
                strength = f_strength
                evidence = {'trigger': 'funding', 'funding_rate': funding}

        if direction is None:
            return None

        if not self._check_state_lock("AMBIENT_SENTIMENT", now):
            return None

        confidence = self.signal_weights.get('retail_extreme', 0.42)

        return SignalCard(
            signal_id=self._make_id('retail_extreme', now),
            category=SignalCategory.POSITIONING,
            sub_type='retail_extreme',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.3,
            timestamp=now,
            decay_half_life_minutes=60.0,
            evidence=evidence,
        )

    # ── POSITIONING: OI Divergence (#12) ────────────────────────────────

    def _detect_oi_divergence(self, curr: Dict[str, Any],
                               prev: Optional[Dict[str, Any]],
                               now: datetime) -> Optional[SignalCard]:
        if not prev:
            return None
        oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
        price_delta = (curr['price_dynamics']['current_price'] -
                       prev['price_dynamics']['current_price'])

        # Epsilon guard: reject exact/no-change cases (float == 0 is unreliable at 1e-16)
        if abs(oi_delta) <= 1e-10 or abs(price_delta) <= 1e-10:
            return None
        # Filter micro-noise: require meaningful OI change before calling divergence
        if abs(oi_delta) <= 0.01:
            return None
        # Must be divergent: OI and price move OPPOSITE
        if (oi_delta > 0 and price_delta > 0) or (oi_delta < 0 and price_delta < 0):
            return None

        direction = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
        strength = min(abs(oi_delta) / 0.03, 1.0)
        confidence = self.signal_weights.get('oi_divergence', 0.70)

        return SignalCard(
            signal_id=self._make_id('oi_divergence', now),
            category=SignalCategory.POSITIONING,
            sub_type='oi_divergence',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.5,
            timestamp=now,
            decay_half_life_minutes=15.0,
            evidence={'oi_delta': oi_delta, 'price_delta': price_delta},
        )

    # ── POSITIONING: OI Surge (#13) ─────────────────────────────────────

    def _detect_oi_surge(self, curr: Dict[str, Any],
                          prev: Optional[Dict[str, Any]],
                          now: datetime) -> Optional[SignalCard]:
        oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
        if abs(oi_delta) <= 0.02:
            return None
        if not prev:
            return None
        price_delta = (curr['price_dynamics']['current_price'] -
                       prev['price_dynamics']['current_price'])
        # Must be aligned: OI and price same direction
        if (oi_delta > 0 and price_delta <= 0) or (oi_delta < 0 and price_delta >= 0):
            return None

        direction = Direction.BULLISH if price_delta > 0 else Direction.BEARISH
        strength = min((abs(oi_delta) - 0.02) / 0.04, 1.0)
        confidence = self.signal_weights.get('oi_surge', 0.55)

        return SignalCard(
            signal_id=self._make_id('oi_surge', now),
            category=SignalCategory.POSITIONING,
            sub_type='oi_surge',
            direction=direction,
            strength=strength,
            confidence=confidence,
            urgency=0.4,
            timestamp=now,
            decay_half_life_minutes=20.0,
            evidence={'oi_delta': oi_delta, 'price_delta': price_delta},
        )

    # ── CROSS-SYMBOL / Re-evaluation ───────────────────────────────────

    def reevaluate_with_boost(self, boosted_signals: List[SignalCard],
                              metrics: Dict[str, Any]) -> Optional['TriggerResult']:
        """Public entry point for cross-symbol Leader Sync re-evaluation.

        Called by SniperDaemon when a correlated leader symbol triggers.
        Recomputes confluence with the boost signal included, re-runs the
        pre-AI gate, and returns a new TriggerResult if the boost tips the
        follower over threshold. Returns None if still below threshold or
        gate fails.
        """
        regime = self._determine_regime(metrics)
        confluence_score, dominant_direction, should_trigger = self.engine.evaluate(
            boosted_signals, regime, is_cooldown_active=False
        )
        if not should_trigger:
            return None

        gate_result, gate_reason = self._run_pre_ai_gate(
            metrics, boosted_signals, dominant_direction, regime
        )
        if gate_result == 'FAIL':
            return None

        situation_brief = self._build_situation_brief(
            boosted_signals, confluence_score, dominant_direction, regime, gate_result
        )
        cooldown_mins = self._get_regime_cooldown(regime)

        return TriggerResult(
            triggered=True,
            confluence_score=confluence_score,
            confluence_direction=dominant_direction,
            signals=boosted_signals,
            active_signals=[s for s in boosted_signals
                           if s.strength >= 0.15 and s.sub_type != 'leader_sync'],
            gate_result=gate_result,
            gate_reason=gate_reason,
            situation_brief=situation_brief,
            cooldown_minutes=cooldown_mins,
        )

    def apply_leader_sync(self, own_signals: List[SignalCard],
                          leader_confluence_score: float,
                          leader_direction: Direction,
                          correlation: float,
                          now: datetime) -> Optional[SignalCard]:
        """Amplify existing weak directional alignment when leader fires."""
        if leader_confluence_score <= 0:
            return None

        aligned = [s for s in own_signals if s.direction == leader_direction]
        if not aligned:
            return None

        boost = min(leader_confluence_score * correlation * 0.25, 0.10)
        confidence = self.signal_weights.get('leader_sync', 0.40)

        return SignalCard(
            signal_id=self._make_id('leader_sync', now),
            category=SignalCategory.CROSS_SYMBOL,
            sub_type='leader_sync',
            direction=leader_direction,
            strength=boost,
            confidence=confidence,
            urgency=0.5,
            timestamp=now,
            decay_half_life_minutes=8.0,
            evidence={'leader_score': leader_confluence_score, 'correlation': correlation},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SIGNAL DIAGNOSTICS — per-pulse compact log of all detector key metrics
    # ═══════════════════════════════════════════════════════════════════════

    def _log_signal_diagnostics(self, metrics: Dict[str, Any],
                                 fresh_signals: List[SignalCard]) -> None:
        """Log a compact per-pulse summary of key decision metrics for all 14
        signal detectors.  Fired detectors show their strength; silent detectors
        show the primary rejection metric vs threshold so operators can tune
        sensitivity or detect silent failures."""
        fired = {s.sub_type: s for s in fresh_signals}
        parts: List[str] = []

        # ── FLOW category ──
        cvd = metrics['sentiment_signals']['cvd_intensity_ratio']
        cvd_thresh = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        parts.append(f"cvd={cvd:+.3f}")

        s = fired.get('cvd_momentum')
        parts.append(f"cvd_momentum={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<={cvd_thresh}'}")

        s = fired.get('cvd_divergence')
        parts.append(f"cvd_divergence={'F:'+str(round(s.strength,2)) if s else 'R:no-prev/div-low'}")
        s = fired.get('cvd_absorption')
        parts.append(f"cvd_absorption={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<=extreme'}")
        s = fired.get('taker_imbalance')
        taker_thresh = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {}).get('taker_imbalance', 0.20)
        parts.append(f"taker_imb={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<={taker_thresh}'}")

        # ── ENERGY category ──
        vii = metrics['price_dynamics']['volatility_intensity_index']
        vpr = metrics['market_regime']['volume_participation_ratio']
        parts.append(f"vii={vii:.2f},vpr={vpr:.2f}")

        s = fired.get('volatility_surge')
        vol_base = self.regime_cfg['volatility']['volatility_baseline_ratio']
        vol_thresh = self.regime_cfg['volume']['volume_participation_threshold']
        parts.append(f"vol_surge={'F:'+str(round(s.strength,2)) if s else f'R:vii<={vol_base}|vpr<={vol_thresh}'}")

        sf = metrics['market_regime']['squeeze_factor']
        sq_thresh = (self.regime_cfg['volatility']['squeeze_threshold'] *
                     self.sniper_cfg['probes']['squeeze_trigger_multiplier'])
        s = fired.get('squeeze')
        parts.append(f"squeeze={'F:'+str(round(s.strength,2)) if s else f'R:sf={sf:.3f}>={sq_thresh:.3f}'}")

        # ── STRUCTURAL category ──
        price = metrics['price_dynamics']['current_price']
        atr = metrics['price_dynamics'].get('atr_macro', 0)
        topo = metrics['volume_profile']
        anchors = metrics.get('structural_anchors', {})
        parts.append(f"price={price:.1f},atr={atr:.2f}")

        # boundary_test
        s = fired.get('boundary_test')
        if atr > 0:
            dist_vh = abs(price - topo['vah']) / atr
            dist_val = abs(price - topo['val']) / atr
            prox_thresh = self.sniper_cfg['proximity']['vah_val_atr']
            parts.append(f"boundary_test={'F:'+str(round(s.strength,2)) if s else f'R:dist_vh={dist_vh:.1f},dist_val={dist_val:.1f}>={prox_thresh}'}")
        else:
            parts.append("boundary_test=R:atr=0")

        # poc_gravity
        poc_dist = anchors.get('poc_dist_atr', 0)
        poc_thresh = self.sniper_cfg['proximity']['poc_atr']
        s = fired.get('poc_gravity')
        parts.append(f"poc_gravity={'F:'+str(round(s.strength,2)) if s else f'R:poc_dist={abs(poc_dist):.2f}>={poc_thresh}'}")

        # liquidation_hunt — already tracked via evidence in SignalCard, just show count
        s = fired.get('liquidation_hunt')
        parts.append(f"liq_hunt={'F:'+str(round(s.strength,2)) if s else 'R:no-cluster-in-range'}")

        # trend_pullback
        trend = metrics['market_regime'].get('trend_intensity', 0)
        strong_t = self.regime_cfg['trend']['trend_intensity_strong']
        s = fired.get('trend_pullback')
        parts.append(f"trend_pullback={'F:'+str(round(s.strength,2)) if s else f'R:trend={abs(trend):.3f}<={strong_t}'}")

        # ── POSITIONING category ──
        ls = metrics['sentiment_signals'].get('ls_ratio_micro', 1.0)
        funding = metrics['sentiment_signals'].get('funding_rate', 0.0)
        parts.append(f"ls={ls:.2f},fund={funding:.4f}")

        s = fired.get('retail_extreme')
        ls_imb = self.regime_cfg['imbalance']['long_short_imbalance_ratio']
        ls_short = self.regime_cfg['imbalance']['short_heavy_imbalance_ratio']
        fund_ext = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        parts.append(f"retail_ext={'F:'+str(round(s.strength,2)) if s else f'R:ls<={ls_imb}&ls>={ls_short}&|fund|<={fund_ext}'}")

        s = fired.get('oi_divergence')
        parts.append(f"oi_div={'F:'+str(round(s.strength,2)) if s else 'R:no-div/no-prev'}")
        s = fired.get('oi_surge')
        oi_delta = metrics['sentiment_signals'].get('oi_delta_micro', 0.0)
        parts.append(f"oi_surge={'F:'+str(round(s.strength,2)) if s else f'R:oi_delta={abs(oi_delta):.4f}<=0.02'}")

        logger.info("[%s] SIGNAL DIAG | %s", self.symbol, " | ".join(parts))

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN EVALUATE — replaces old (bool, str, str) method
    # ═══════════════════════════════════════════════════════════════════════

    def evaluate(self, current_metrics: Dict[str, Any],
                 prev_metrics: Optional[Dict[str, Any]] = None) -> TriggerResult:
        """
        Evaluate current market state and return a TriggerResult.

        Algorithm:
        1. Check adaptive cooldown
        2. Detect all 13 direct signal types
        3. Merge with decayed signal memory
        4. Compute confluence via ConfluenceEngine
        5. Check emergency override and cooldown break
        6. Run Pre-AI gate if triggering
        7. Build pre-brief if passing
        8. Return TriggerResult
        """
        now = datetime.now(timezone.utc)

        # 0. Determine regime
        regime = self._determine_regime(current_metrics)

        # 1. Cooldown check
        cooldown_active, cooldown_reason = self._check_adaptive_cooldown(now, regime)

        # 2. Detect all signals from current pulse
        fresh_signals: List[SignalCard] = []
        for detector in self._signal_detectors:
            try:
                card = detector(current_metrics, prev_metrics, now)
                if card:
                    fresh_signals.append(card)
            except Exception as e:
                logger.warning(f"detector {detector.__name__} failed | error={e}")

        # 2b. Per-pulse signal diagnostics — compact log of all detector key metrics
        self._log_signal_diagnostics(current_metrics, fresh_signals)

        # 3. Merge with decayed signal memory
        all_signals = self.memory.ingest(fresh_signals, now)

        # 4. Check cooldown break (stacked signals or strength ratio)
        cooldown_break = False
        if cooldown_active:
            cooldown_break = self._check_cooldown_break(fresh_signals, regime)

        # 5. Compute confluence
        effective_cooldown = cooldown_active and not cooldown_break
        self.cooldown_active = effective_cooldown
        confluence_score, dominant_direction, should_trigger = self.engine.evaluate(
            all_signals, regime, is_cooldown_active=effective_cooldown
        )

        # 6. Pre-AI Gate
        gate_result = "PASS"
        gate_reason = ""
        if should_trigger:
            gate_result, gate_reason = self._run_pre_ai_gate(
                current_metrics, all_signals, dominant_direction, regime
            )
            if gate_result == "FAIL":
                should_trigger = False

        # 7. Build situation brief
        situation_brief = None
        if should_trigger:
            situation_brief = self._build_situation_brief(
                all_signals, confluence_score, dominant_direction, regime, gate_result
            )

        # 8. Cooldown for this trigger
        cooldown_mins = self._get_regime_cooldown(regime)

        result = TriggerResult(
            triggered=should_trigger,
            confluence_score=confluence_score,
            confluence_direction=dominant_direction,
            signals=all_signals,
            active_signals=[s for s in fresh_signals if s.strength >= 0.15],
            gate_result=gate_result,
            gate_reason=gate_reason or (cooldown_reason if cooldown_active and not should_trigger else ""),
            situation_brief=situation_brief,
            cooldown_minutes=cooldown_mins,
        )

        if should_trigger:
            memory_signal_count = len(all_signals) - len(fresh_signals)
            logger.info(
                f"[{self.symbol}] WAKE | dir={dominant_direction.value} | "
                f"confluence={confluence_score:.2f} | "
                f"fresh={len(fresh_signals)} | memory={memory_signal_count} | "
                f"active={[s.sub_type for s in result.active_signals]} | "
                f"gate={gate_result} | regime={regime}"
            )

        return result

    def set_triggered(self, result: TriggerResult, trigger_type: str = "ACTIVE"):
        """Record trigger time and score for cooldown tracking.

        trigger_type controls cooldown duration:
        - TRADED / ACTIVE_POSITION → full regime cooldown (capital deployed)
        - NEUTRAL / OBSERVE_ONLY → shortened (× neutral_multiplier)
        """
        self.last_trigger_time = datetime.now(timezone.utc)
        self.last_trigger_score = result.confluence_score
        self._last_trigger_type = trigger_type
        self.cooldown_active = True
