"""
BinaryStar Sniper Trigger — Signal Stack Architecture.

Replaces the old binary-trigger model with a continuous multi-signal confluence
engine. 10 signal detectors are evaluated per pulse, each scored on
a 0–1 continuum, stacked directionally, and only fire an AI session when the
confluence score exceeds a regime-adaptive threshold.

See docs/trigger-design-20260625.md for the full design specification.
"""

import math
from collections import deque
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple, Optional, List

from src.sniper.adaptive import RobustWindows
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

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
    sub_type: str
    direction: Direction
    strength: float                         # 0.0–1.0
    weight: float                           # 0.0–1.0, detector weight
    timestamp: datetime
    decay_half_life_minutes: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    # Information source (see SIGNAL_SOURCES). Left empty by callers; derived
    # from sub_type so the mapping lives in exactly one place.
    source: str = ""

    def __post_init__(self) -> None:
        if not self.source:
            self.source = SIGNAL_SOURCES.get(self.sub_type, DEFAULT_SIGNAL_SOURCE)

    @property
    def weighted_score(self) -> float:
        """Effective score used in confluence stacking."""
        result = self.strength * self.weight
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
    gate_result: str                        # "PASS" | "FAIL" | "SKIPPED"
    situation_brief: Optional[Dict[str, Any]]  # None if not triggered
    cooldown_minutes: float
    gate_reason: str = ""                   # why PASS/FAIL/SKIPPED — surfaced to state file
    # Non-empty when the source-breadth gate is in shadow mode and *would* have
    # blocked this pulse.  Kept separate from gate_reason so the UI can show
    # "the new rule would have said no" without pretending it is the reason the
    # pulse did not wake.
    gate_shadow: str = ""


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


@dataclass
class StructuralFingerprint:
    """Snapshot of market structure at trigger time.

    Compared on subsequent cooldown break attempts.  If unchanged,
    the break is rejected to avoid re-triggering on the same market
    conditions that already produced a NEUTRAL or failed session.
    """
    vah: float
    val: float
    poc: float
    price: float
    atr_macro: float
    regime: str
    timestamp: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Calibration Constants — detector strength saturation curves
# ═══════════════════════════════════════════════════════════════════════════
# These control how raw measurements map to 0–1 signal strengths.
# They are NOT config-driven because they encode the physical relationship
# between each measurement type and "how extreme is this?" — changing them
# would alter the signal stack's calibration, not its sensitivity.
# For sensitivity tuning, use config thresholds and weights instead.

# FLOW — CVD-based detectors saturate fast (CVD is noisy, needs aggressive scaling)
CVD_SATURATION_FACTOR = 3.0
CVD_ABSORPTION_SATURATION = 1.5
CVD_ABSORPTION_MIN_DENOM = 0.15

# SIZE — Z-score to strength mapping
LARGE_TRADE_SATURATION = 2.0
MIN_LARGE_TRADE_SAMPLES = 5

# ENERGY
VOLATILITY_SATURATION = 2.0
SQUEEZE_DECLINE_THRESHOLD = 0.98

# STRUCTURAL — proximity-based detectors saturate slowly (ATR distance is precise)
BOUNDARY_STRENGTH_SCALE = 0.25
LIQUIDATION_STRENGTH_SCALE = 0.15

# POSITIONING
FUNDING_SATURATION = 4.0
OI_DIVERGENCE_SATURATION = 0.03
OI_SURGE_MIN_DELTA = 0.02
OI_SURGE_SATURATION = 0.04

# General
MIN_STACK_STRENGTH = 0.15
# Signals whose direction is literally sign(cvd).  They are not independent
# confirmations of each other — cvd_momentum and large_trade were same-direction
# in 100% of the pulses where both fired (XAUT 91/91, BTC 62/62, 2026-09-05~17).
# Used by the optional "independent direction" gate, see
# docs/sniper_gate_review_and_plan_20260917.md.
CVD_DERIVED_SUBTYPES = frozenset({'cvd_momentum', 'large_trade', 'volatility_surge'})
ABSORPTION_PRICE_STALL_ATR = 0.3
LEADER_SYNC_CAP = 0.10
LEADER_SYNC_SCALE = 0.25
CVD_NEUTRAL_EPSILON = 0.01

# Provenance: which *information source* a detector's direction ultimately comes
# from.  The count gate asks for breadth ("≥3 same-direction signals"), but
# signals sharing a source are not independent confirmations — cvd_momentum,
# cvd_absorption, large_trade and volatility_surge all derive their direction
# from the same order-flow reading, so four of them still carry one piece of
# information.  Declaring the source lets the gate ask for breadth in the unit
# that actually matters.
#
# Grouping is by *direction provenance*, not by subject matter: volatility_surge
# is a volatility detector but takes its direction from sign(cvd), so it belongs
# to "flow".  See docs/sniper_signal_stack_redesign_20261014.md §2.1.
SIGNAL_SOURCES: Dict[str, str] = {
    'cvd_momentum': 'flow',
    'cvd_absorption': 'flow',
    'large_trade': 'flow',
    'volatility_surge': 'flow',
    # NOT flow: its direction is contrarian *price* (BEARISH if price rose),
    # not sign(cvd).  Grouping it with the four sign(cvd) detectors understated
    # the independent-source count and made the shadow gate read as blocking
    # more often than it should.
    'cvd_divergence': 'divergence',
    'squeeze': 'volatility',
    'boundary_test': 'structure',
    'liquidation_hunt': 'liquidity',
    'positioning_extreme': 'positioning',
    'leader_sync': 'cross_symbol',
}
DEFAULT_SIGNAL_SOURCE = 'unknown'


# ═══════════════════════════════════════════════════════════════════════════
# Confluence Engine
# ═══════════════════════════════════════════════════════════════════════════

class ConfluenceEngine:
    """Evaluates a stack of SignalCards and produces a confluence score + trigger decision."""

    def __init__(self, config: dict):
        # config is the signal_stack sub-dict
        self.base_threshold = config.get('trigger_threshold', 0.35)
        self.effective_threshold = self.base_threshold  # updated per-evaluate with regime modifier
        self.emergency_threshold = config.get('emergency_threshold', 0.85)
        self.regime_modifiers = config.get('regime_modifiers', {
            'trending': 0.85, 'ranging': 1.0, 'squeeze': 0.75, 'chaos': 1.50,
        })
        self.signal_weights = config.get('weights', {})
        self.min_strength_for_stack = MIN_STACK_STRENGTH

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

        if bullish_score > bearish_score:
            dominant = Direction.BULLISH
            raw_score = bullish_score
        elif bearish_score > bullish_score:
            dominant = Direction.BEARISH
            raw_score = bearish_score
        else:
            return 0.0, Direction.NEUTRAL

        noise_factor = 1.0 - (bullish_score * bearish_score)
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
        self.effective_threshold = self.base_threshold * modifier
        effective_threshold = self.effective_threshold

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
    9 signal types, stacks them directionally via ConfluenceEngine, and fires
    an AI session only when confluence exceeds a regime-adaptive threshold.
    """

    # Cross-symbol correlation matrix: leader → {follower: coefficient}.
    # Only leaders listed as keys can propagate to followers.  Currently empty
    # (all symbols trade independently); add entries when introducing ETH/SOL.
    #
    # Usage — when a leader symbol fires (WAKE), the daemon pushes a leader_sync
    # signal card to each follower listed under that leader.  The boost strength
    # is capped at 0.10 and only nudges a follower that is already close to its
    # own trigger threshold.  A single leader_sync card cannot cause a trigger on
    # its own.
    #
    # Calibration — effective correlation range is 0.50–0.80 (cap flattens
    # everything above 0.80).  For majors that track a common leader
    # (ETH, SOL), 0.70 is a good starting point.  For weaker relationships,
    # 0.50–0.60 gives a barely-felt nudge.  Tune based on backtest results.
    #
    # Example:
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
        self._last_trigger_type: Optional[str] = None  # TRADED | NEUTRAL | OBSERVE_ONLY | ACTIVE_POSITION | FAILED
        self.cooldown_active: bool = False
        self.symbol: Optional[str] = symbol

        # Config loading
        from src.utils.pipeline_utils import load_combined_config, load_global_config
        self.strat_cfg = strategy_cfg if strategy_cfg is not None else load_combined_config()
        self.global_cfg = global_cfg if global_cfg is not None else load_global_config()

        # Apply per-symbol overrides if symbol is provided and configs were loaded as base
        if self.symbol:
            from src.config.symbol_resolver import resolve_config, is_symbol_configured
            if is_symbol_configured(self.symbol):
                if strategy_cfg is None:
                    self.strat_cfg = resolve_config(self.strat_cfg, self.symbol)
                if global_cfg is None:
                    self.global_cfg = resolve_config(self.global_cfg, self.symbol)

        self.regime_cfg = self.strat_cfg['regime_parameters']
        self.sniper_cfg = self.global_cfg['sniper']

        # State lock duration: one macro candle
        macro_interval = self.strat_cfg['analysis_window']['macro_context']['time_interval']
        self.macro_hours = self._parse_interval_to_minutes(macro_interval) / 60.0

        # Confluence engine (receives signal_stack sub-config only)
        self.engine = ConfluenceEngine(self.sniper_cfg.get('signal_stack', {}))

        # Signal memory for inter-pulse decay
        self.memory = SignalMemory()

        # State locks for structural/sentiment patterns (ported from old trigger)
        self.state_locks: Dict[str, datetime] = {}

        # Rolling stats for large_trade detector (per-symbol deque of avg_trade_size)
        large_trade_cfg = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {})
        self._trade_size_window = deque(maxlen=large_trade_cfg.get('large_trade_lookback', 30))

        # Pulse history for cvd_divergence. That detector must compare samples one
        # *micro candle* apart rather than one pulse apart — see _cvd_reference().
        micro_interval = (self.strat_cfg.get('analysis_window', {})
                          .get('micro_context', {}).get('time_interval', '15m'))
        self._cvd_lag_minutes = self._parse_interval_to_minutes(micro_interval)
        # Must reach back at least lag + tolerance; sized against the configured
        # ~2-minute pulse cadence so a longer micro timeframe cannot silently
        # leave the detector permanently dark.
        self._cvd_history: deque = deque(maxlen=max(64, int(self._cvd_lag_minutes) * 3))
        self._cvd_div_reason = "warmup"
        self._gate_shadow = ""

        # Scale-free thresholds.  When disabled every detector keeps its legacy
        # absolute rule, so the switch is behaviour-preserving by construction.
        # See src/sniper/adaptive.py for why the absolute ones had to go.
        adaptive_cfg = self.sniper_cfg.get('signal_stack', {}).get('adaptive', {}) or {}
        self._adaptive_on = bool(adaptive_cfg.get('enabled', False))
        self._z_entry = float(adaptive_cfg.get('z_entry', 2.5))
        self._z_extreme = float(adaptive_cfg.get('z_extreme', 4.0))
        self._adaptive = RobustWindows(
            window_minutes=float(adaptive_cfg.get('window_minutes', 240)),
            min_samples=int(adaptive_cfg.get('min_samples', 30)),
        )
        self._last_z: Dict[str, float] = {}

        # Structural fingerprint for cooldown break noise gate (see spec 2026-07-23)
        self._fingerprint: Optional[StructuralFingerprint] = None

        # Signal weights (convenience accessor)
        self.signal_weights = self.sniper_cfg.get('signal_stack', {}).get('weights', {})

        # Signal decay half-lives (minutes) — keyed by detector sub_type
        self._decay = self.sniper_cfg['signal_stack']['decay']

        # Ordered signal detection registry
        self._signal_detectors = [
            # FLOW (fastest, most direct)
            self._detect_cvd_momentum,
            self._detect_cvd_divergence,
            self._detect_cvd_absorption,
            # SIZE
            self._detect_large_trade,
            # ENERGY
            self._detect_volatility_surge,
            self._detect_squeeze,
            # STRUCTURAL
            self._detect_boundary_test,
            self._detect_liquidation_hunt,
            # POSITIONING
            self._detect_positioning_extreme,
        ]

        logger.info(
            f"Signal Stack active | base={self.engine.base_threshold} | "
            f"emergency={self.engine.emergency_threshold} | "
            f"detectors={len(self._signal_detectors)}"
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def reset_state(self) -> None:
        """Drop every piece of cross-pulse state.

        Called after a long gap (host suspend, network outage, manual pause).
        Decayed signal memory and a stale cooldown are meaningless after hours,
        and the trigger would otherwise resume as if no time had passed.
        """
        self.memory = SignalMemory()
        self.last_trigger_time = None
        self.last_trigger_score = None
        self._last_trigger_type = None
        self.cooldown_active = False
        self.state_locks.clear()
        self._fingerprint = None
        self._cvd_history.clear()
        self._cvd_div_reason = "warmup"
        self._adaptive.clear()
        self._last_z.clear()

    def _cvd_reference(self, now: datetime) -> Optional[Tuple[datetime, float, float]]:
        """Buffered (timestamp, cvd, price) from one micro candle ago.

        ``cvd_intensity_ratio`` is net taker flow over the last four 15-minute
        candles, so it steps discontinuously whenever a candle closes: a full
        candle leaves the window and an empty one enters, shrinking the
        denominator and amplifying the ratio.  Comparing consecutive 2-minute
        pulses therefore mostly measures that rollover — measured over
        2026-09-18→10-05, ``|ΔCVD|`` in the first 2 min after a candle close is
        3.7x the mid-candle value, cvd_divergence fired 15x (XAUT) / 57x (BTC)
        more often there, and 70% / 90% of all its fires landed in those 13% of
        the time.

        Sampling one candle apart keeps both endpoints at the same point of the
        rollover cycle, which cancels the mean shift (measured 3.7x → 1.11x for
        XAUT; 3.8x → 1.15x for BTC) and leaves the genuine "one candle rolled
        through" delta.  BTC keeps a residual tail bias — see its threshold
        comment in config/symbol_config.yaml.

        Returns None during warm-up (including just after reset_state()), so the
        detector is simply dark until it has a same-phase sample to compare to.
        """
        tol = timedelta(minutes=self._cvd_lag_minutes / 6.0)
        target = now - timedelta(minutes=self._cvd_lag_minutes)
        best: Optional[Tuple[datetime, float, float]] = None
        for stamp, cvd, price in self._cvd_history:
            gap = abs(stamp - target)
            if gap > tol or (best is not None and gap >= abs(best[0] - target)):
                continue
            best = (stamp, cvd, price)
        return best

    def _record_adaptive_samples(self, metrics: Dict[str, Any], now: datetime) -> None:
        """Feed every adaptive window, unconditionally.

        This must run for every pulse, not only for pulses where a detector
        fires — otherwise the baseline would be estimated from the detector's
        own past triggers and drift with them.
        """
        if not self._adaptive_on:
            return
        sentiment = metrics.get('sentiment_signals') or {}
        price_dyn = metrics.get('price_dynamics') or {}
        regime_dyn = metrics.get('market_regime') or {}
        cvd = sentiment.get('cvd_intensity_ratio')
        for name, value in (
            ('cvd', cvd),
            ('ls', sentiment.get('ls_ratio_micro')),
            ('funding', sentiment.get('funding_rate')),
            ('oi_delta', sentiment.get('oi_delta_micro')),
            ('avg_trade_size', sentiment.get('avg_trade_size')),
            ('vii', price_dyn.get('volatility_intensity_index')),
            ('vpr', regime_dyn.get('volume_participation_ratio')),
        ):
            self._adaptive.update(name, value, now)
        # Derived: how far the order-flow reading moved over one candle.
        ref = self._cvd_reference(now)
        if ref is not None and cvd is not None:
            self._adaptive.update('cvd_delta', cvd - ref[1], now)

    def _adaptive_z(self, name: str, value: Optional[float]) -> float:
        """Robust z of `value` in its window (0.0 when disabled or warming up).

        Callers use `abs(z) > k`, so 0.0 means "not extreme", which is the
        fail-safe answer during warm-up.
        """
        if not self._adaptive_on:
            return 0.0
        return self._adaptive.z(name, value)

    def _record_cvd_sample(self, metrics: Dict[str, Any], now: datetime) -> None:
        """Buffer this pulse's CVD ratio and price for the next candle-lagged comparison."""
        sentiment = metrics.get('sentiment_signals') or {}
        price = (metrics.get('price_dynamics') or {}).get('current_price')
        cvd = sentiment.get('cvd_intensity_ratio')
        if cvd is None or not price:
            return
        self._cvd_history.append((now, float(cvd), float(price)))

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
        lock_hours = self.macro_hours
        if lock_key in self.state_locks:
            lock_time, lock_duration = self.state_locks[lock_key]
            elapsed_hours = (now - lock_time).total_seconds() / 3600.0
            if elapsed_hours < lock_duration:
                return False
        self.state_locks[lock_key] = (now, lock_hours)
        return True

    def _signal_cfg(self, *path, default=None):
        """Walk sniper_cfg → signal_stack → ... safely. e.g. _signal_cfg('thresholds', 'cvd_extreme_threshold', default=0.18)."""
        node = self.sniper_cfg.get('signal_stack', {})
        for key in path:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        return node if node else default

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
        regime_minutes = cooldown_cfg.get('regime_base_minutes', {})
        cooldown_mins = regime_minutes[regime]

        # Outcome-aware: NEUTRAL/OBSERVE_ONLY get shortened cooldown (no capital deployed)
        if self._last_trigger_type in ("NEUTRAL", "OBSERVE_ONLY"):
            neutral_mult = cooldown_cfg.get('neutral_multiplier', 1.0)
            cooldown_mins = cooldown_mins * neutral_mult

        # FAILED: session errored (e.g. MaxIterationsError) — short fixed backoff,
        # not regime-dependent. The purpose is solely to prevent re-trigger storms.
        if self._last_trigger_type == "FAILED":
            cooldown_mins = cooldown_cfg.get('failure_cooldown_minutes', 3)

        elapsed = (now - self.last_trigger_time).total_seconds() / 60.0

        if elapsed < cooldown_mins:
            return True, f"COOLDOWN_{regime.upper()} ({elapsed:.1f}m/{cooldown_mins}m)"

        return False, ""

    def _get_regime_cooldown(self, regime: str) -> float:
        """Return the cooldown that will be applied after a trigger in this regime."""
        cooldown_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {})
        regime_minutes = cooldown_cfg.get('regime_base_minutes', {})
        return regime_minutes[regime]

    def _check_cooldown_break(self, fresh_signals: List[SignalCard]) -> bool:
        """Check if cooldown should break due to stacked signals or strength ratio."""
        cooldown_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {})

        # Break if 3+ fresh signals stack in same direction
        stacked_count = cooldown_cfg.get('stacked_break_count', 3)
        dir_counts: Dict[Direction, int] = {}
        for s in fresh_signals:
            if s.direction != Direction.NEUTRAL and s.strength >= MIN_STACK_STRENGTH:
                dir_counts[s.direction] = dir_counts.get(s.direction, 0) + 1
        for direction, count in dir_counts.items():
            if count >= stacked_count:
                logger.debug(
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
                    logger.debug(
                        "[%s] cooldown break: strength_ratio | signal=%s "
                        "weighted=%.3f threshold=%.3f (last_score=%.3f × %.1f)",
                        self.symbol, s.sub_type, s.weighted_score,
                        ratio_threshold, self.last_trigger_score, break_ratio,
                    )
                    return True

        return False

    # ── Structural Fingerprint ────────────────────────────────────────────

    def _save_fingerprint(self, metrics: Dict[str, Any]) -> None:
        """Record current market structure snapshot for later stale-check."""
        try:
            topo = metrics.get('volume_profile', {})
            dyn = metrics.get('price_dynamics', {})
            vah = topo.get('vah')
            val = topo.get('val')
            poc = topo.get('poc')
            price = dyn.get('current_price')
            atr = dyn.get('atr_macro', 0)
            regime = self._determine_regime(metrics)

            if None in (vah, val, poc, price) or atr is None or atr <= 0:
                logger.info("[%s] _save_fingerprint: incomplete metrics (vah=%s, val=%s, poc=%s, price=%s, atr=%s)",
                               self.symbol, vah, val, poc, price, atr)
                return

            self._fingerprint = StructuralFingerprint(
                vah=vah, val=val, poc=poc, price=price,
                atr_macro=atr, regime=regime,
                timestamp=datetime.now(timezone.utc),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("[%s] _save_fingerprint failed | error=%s: %s", self.symbol, type(e).__name__, e)

    def _structure_is_unchanged(self, metrics: Dict[str, Any]) -> Tuple[bool, str]:
        """True if market structure has NOT changed meaningfully since last trigger.

        Return True -> structure unchanged -> cooldown break should be BLOCKED.
        Return False -> structure changed -> allow break through.
        Returns (bool, delta_summary) where delta_summary describes per-field ratios.
        """
        fp = self._fingerprint
        if fp is None:
            return False, ""

        try:
            # Read thresholds from config
            fp_cfg = self.sniper_cfg.get('signal_stack', {}).get('cooldown', {}).get('structural_fingerprint', {})
            structure_shift_atr = fp_cfg.get('structure_shift_atr', 0.5)
            price_drift_atr = fp_cfg.get('price_drift_atr', 0.7)
            atr_change_ratio = fp_cfg.get('atr_change_ratio', 0.30)

            topo = metrics.get('volume_profile', {})
            dyn = metrics.get('price_dynamics', {})
            atr = dyn.get('atr_macro', fp.atr_macro or 1)
            if atr is None or atr <= 0:
                return False, ""

            # None guard — incomplete metrics mean structure is unmeasurable
            curr_vah = topo.get('vah')
            curr_val = topo.get('val')
            curr_poc = topo.get('poc')
            curr_price = dyn.get('current_price')
            if None in (curr_vah, curr_val, curr_poc, curr_price):
                logger.info("[%s] _fingerprint_is_stale: incomplete metrics, allowing break", self.symbol)
                return False, ""

            # ATR shift > ratio -> volatility regime changed
            atr_shift = abs(atr - fp.atr_macro) / max(fp.atr_macro, 1e-9)
            if atr_shift > atr_change_ratio:
                return False, ""

            # Structural boundary shift > N ATR — single loop over fields
            struct_deltas = {}
            for field, val in [('vah', curr_vah), ('val', curr_val), ('poc', curr_poc)]:
                d = abs(val - getattr(fp, field)) / atr
                struct_deltas[field] = d
                if d > structure_shift_atr:
                    return False, ""

            # Price drift > N ATR
            price_delta = abs(curr_price - fp.price) / atr
            if price_delta > price_drift_atr:
                return False, ""

            # Regime change -> unlock different execution rules
            current_regime = self._determine_regime(metrics)
            if current_regime != fp.regime:
                return False, f"regime_changed:{fp.regime}->{current_regime}"

            # Build delta summary for logging
            deltas = [f"{f}={struct_deltas[f]:.2f}atr" for f in ('vah', 'val', 'poc')]
            deltas.append(f"price={price_delta:.2f}atr")
            return True, ", ".join(deltas)

        except (KeyError, TypeError, ValueError) as e:
            logger.warning("[%s] _fingerprint_is_stale failed | error=%s: %s", self.symbol, type(e).__name__, e)
            return False, ""

    # ── Pre-AI Gate ──────────────────────────────────────────────────────

    def _run_pre_ai_gate(self, curr: Dict[str, Any],
                         signals: List[SignalCard],
                         direction: Direction,
                         regime: str) -> Tuple[str, str]:
        """Deterministic pre-check before spending AI tokens. Returns (result, reason)."""
        gate_cfg = self.sniper_cfg.get('signal_stack', {}).get('gate', {})
        self._gate_shadow = ""

        # 1. Directional sanity
        if gate_cfg.get('directional_sanity', True):
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

        # 2. Chaos survival
        if gate_cfg.get('chaos_survival', True) and regime == 'chaos':
            # Directional momentum signals in chaos are prohibited
            momentum_signals = [s for s in signals
                              if s.sub_type in ('cvd_momentum', 'volatility_surge')
                              and s.direction == direction]
            if momentum_signals and not any(
                s.sub_type in ('squeeze', 'cvd_absorption', 'large_trade') for s in signals
            ):
                return "FAIL", "CHAOS_SURVIVAL: directional momentum prohibited in chaos regime"

        # 3. Minimal active signal convergence — single-signal noise filter.
        # Non-trend regimes (ranging, squeeze, chaos) require at least
        # min_active_non_trend same-direction signals in the trigger direction.
        # Trending requires at least min_active_trend — a bare sanity floor;
        # trend inertia still makes single signals more reliable, so the bar
        # is lower than non-trend regimes.
        # Squeeze signals (direction=NEUTRAL) are naturally excluded by the
        # direction filter — no explicit sub_type exclusion needed.
        same_dir_active = [
            s for s in signals
            if s.direction == direction
            and s.strength >= MIN_STACK_STRENGTH
        ]
        if regime == 'trending':
            min_active = gate_cfg.get('min_active_trend', 0)
            gate_tag = 'MIN_ACTIVE_TREND'
        else:
            min_active = gate_cfg.get('min_active_non_trend', 0)
            gate_tag = 'MIN_ACTIVE_SIGNALS'
        if min_active > 0 and len(same_dir_active) < min_active:
            return "FAIL", (
                f"{gate_tag}: regime={regime} requires ≥{min_active} "
                f"signals in {direction.value} direction, "
                f"got {len(same_dir_active)}"
            )

        # 4. Direction provenance — optional, off by default.  Counting N
        #    same-direction signals is not N independent confirmations when the
        #    directions all come from sign(cvd).  Shadow mode only logs the
        #    extra wakes the rule would remove, so evidence can accumulate
        #    without changing trigger behaviour.
        has_independent = any(s.sub_type not in CVD_DERIVED_SUBTYPES
                              for s in same_dir_active)
        if gate_cfg.get('shadow_require_independent_direction', False) and not has_independent:
            logger.info(
                "[%s] GATE SHADOW | independent-direction rule WOULD BLOCK | "
                "regime=%s | dir=%s | active=%s",
                self.symbol, regime, direction.value,
                [s.sub_type for s in same_dir_active],
            )
        if gate_cfg.get('require_independent_direction', False) and not has_independent:
            return "FAIL", (
                f"MIN_ACTIVE_INDEPENDENT: regime={regime} has "
                f"{len(same_dir_active)} signals in {direction.value} but all derive "
                f"direction from sign(cvd) ({[s.sub_type for s in same_dir_active]})"
            )

        # 5. Source breadth — ask for breadth in *independent information*, not
        #    in signal count.  Counting three detectors that all read the same
        #    order-flow number is one observation, not three.  Shadow by default:
        #    the verdict above is unchanged, we only record what the rule would
        #    have decided so evidence can accumulate at zero risk.
        #    See docs/sniper_signal_stack_redesign_20261014.md §2.3.
        sources = sorted({s.source for s in same_dir_active})
        if regime == 'trending':
            min_sources = gate_cfg.get('min_sources_trend', 0)
        else:
            min_sources = gate_cfg.get('min_sources_non_trend', 0)
        mode = gate_cfg.get('sources_mode', 'off')
        if mode != 'off' and min_sources > 0 and len(sources) < min_sources:
            would = (f"GATE SOURCE {'WOULD BLOCK' if mode == 'shadow' else 'BLOCK'} | "
                     f"regime={regime} requires ≥{min_sources} independent sources | "
                     f"dir={direction.value} | got {len(sources)} ({sources}) | "
                     f"from {[s.sub_type for s in same_dir_active]}")
            if mode == 'shadow':
                logger.info("[%s] %s", self.symbol, would)
                self._gate_shadow = (
                    f"would block: {len(sources)}/{min_sources} independent sources"
                )
            else:
                return "FAIL", would.replace(f"GATE SOURCE BLOCK | ", "MIN_INDEPENDENT_SOURCES: ")

        return "PASS", ""

    # ── Pre-Brief Builder ────────────────────────────────────────────────

    def _build_situation_brief(self, all_signals: List[SignalCard],
                         confluence_score: float,
                         direction: Direction) -> Dict[str, Any]:
        """Build the pre-brief JSON injected into the SessionAgent's observation."""
        activated_by = []
        for s in sorted(all_signals, key=lambda x: x.weighted_score, reverse=True)[:5]:
            if s.direction != Direction.NEUTRAL or s.sub_type == 'squeeze':
                activated_by.append({
                    "signal": s.sub_type,
                    "direction": s.direction.value,
                    "strength": round(s.strength, 2),
                })

        return {
            "confluence_score": round(confluence_score, 2),
            "confluence_direction": direction.value,
            "activated_by": activated_by,
        }


    # ═══════════════════════════════════════════════════════════════════════
    # SIGNAL DETECTORS (9 direct + 1 cross-symbol = 10 total)
    # ═══════════════════════════════════════════════════════════════════════

    def _make_id(self, sub_type: str, now: datetime) -> str:
        return f"{sub_type}_{now.strftime('%Y%m%d_%H%M%S')}"

    # ── FLOW: CVD Momentum (#1) ────────────────────────────────────────

    def _detect_cvd_momentum(self, curr: Dict[str, Any],
                              prev: Optional[Dict[str, Any]],
                              now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        base_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        extreme_threshold = self._signal_cfg('thresholds', 'cvd_extreme_threshold', default=0.18)

        z = self._adaptive_z('cvd', cvd)
        if self._adaptive_on:
            # Scale-free: |cvd| relative to this symbol's own recent spread.
            # Path A keeps the "still growing" idea, but expressed against the
            # previous pulse's z instead of a fixed 1.4x ratio (that ratio was
            # the reason this detector fired on 29% of XAUT pulses).
            path_a = abs(z) > self._z_entry and abs(z) >= abs(self._last_z.get('cvd', 0.0))
            path_b = abs(z) > self._z_extreme
            strength_a = min(abs(z) / (self._z_entry * CVD_SATURATION_FACTOR), 1.0) if path_a else 0.0
            strength_b = min(abs(z) / (self._z_extreme * CVD_SATURATION_FACTOR), 1.0) if path_b else 0.0
        else:
            # Path A (growth): CVD above base threshold AND still growing
            path_a = False
            if abs(cvd) > base_threshold:
                if prev:
                    prev_cvd = prev['sentiment_signals']['cvd_intensity_ratio']
                    growth_ratio = self.sniper_cfg['probes']['cvd_growth_significance_ratio']
                    if abs(cvd) >= abs(prev_cvd) * growth_ratio:
                        path_a = True
                # else: first pulse — no growth check possible; require extreme path (path_b)

            # Path B (extreme static): CVD above the higher extreme threshold
            path_b = abs(cvd) > extreme_threshold
            strength_a = min(abs(cvd) / (base_threshold * CVD_SATURATION_FACTOR), 1.0) if path_a else 0.0
            strength_b = min((abs(cvd) - extreme_threshold) / extreme_threshold, 1.0) if path_b else 0.0

        self._last_z['cvd'] = abs(z)

        if not (path_a or path_b):
            return None

        direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        strength = max(strength_a, strength_b)
        weight = self.signal_weights.get('cvd_momentum')

        trigger_path = 'extreme' if path_b and strength_b >= strength_a else 'growth'
        return SignalCard(
            signal_id=self._make_id('cvd_momentum', now),
            sub_type='cvd_momentum',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['cvd_momentum'],
            evidence={'cvd_intensity': cvd, 'threshold': base_threshold,
                      'trigger_path': trigger_path},
        )

    # ── FLOW: CVD Divergence (#2) ──────────────────────────────────────

    def _detect_cvd_divergence(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        # `prev` is deliberately unused: comparing against the previous pulse
        # measures the CVD window rollover rather than order flow. See
        # _cvd_reference(). The parameter stays for the uniform detector signature.
        ref = self._cvd_reference(now)
        if not ref:
            self._cvd_div_reason = "warmup(no same-phase sample yet)"
            return None
        ref_stamp, ref_cvd, ref_price = ref

        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        cvd_delta = cvd - ref_cvd
        # Default mirrors config/global_config.yaml so a missing key behaves the
        # same as an unconfigured symbol rather than silently picking a
        # different operating point.
        threshold = self._signal_cfg('thresholds', 'cvd_divergence_candle_delta', default=0.30)
        age = (now - ref_stamp).total_seconds() / 60.0
        driver = abs(cvd_delta)
        if self._adaptive_on:
            # Judged against the symbol's own distribution of one-candle flow
            # changes.  This also removes the BTC problem where a fixed
            # threshold had to sit in a thin, bounded tail (max |dCVD| 0.449)
            # and therefore stayed partly clock-driven even after the rollover
            # fix — a relative threshold has no such edge to sit on.
            driver = abs(self._adaptive_z('cvd_delta', cvd_delta))
            threshold = self._z_entry
        if driver <= threshold:
            # Report the driver that is actually in force: in adaptive mode that
            # is the z-score, and printing the raw delta next to a z threshold
            # would read like a bug in the log.
            label = (f"|z|={driver:.2f}" if self._adaptive_on
                     else f"|dCVD|={abs(cvd_delta):.3f}")
            self._cvd_div_reason = f"{label}<={threshold} (ref {age:.0f}m ago)"
            return None

        price_delta = curr['price_dynamics']['current_price'] - ref_price
        if not ((price_delta > 0 and cvd_delta < 0) or (price_delta < 0 and cvd_delta > 0)):
            self._cvd_div_reason = f"no divergence (dCVD={cvd_delta:+.3f}, dPrice={price_delta:+.2f})"
            return None

        direction = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
        strength = min(driver / (threshold * CVD_SATURATION_FACTOR), 1.0)
        weight = self.signal_weights.get('cvd_divergence')
        self._cvd_div_reason = f"F:{strength:.2f}"

        return SignalCard(
            signal_id=self._make_id('cvd_divergence', now),
            sub_type='cvd_divergence',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['cvd_divergence'],
            evidence={'cvd_delta': cvd_delta, 'price_delta': price_delta,
                      'threshold': threshold, 'ref_age_minutes': round(age, 1)},
        )

    # ── FLOW: CVD Absorption (#3) ──────────────────────────────────────

    def _detect_cvd_absorption(self, curr: Dict[str, Any],
                                prev: Optional[Dict[str, Any]],
                                now: datetime) -> Optional[SignalCard]:
        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        extreme_threshold = self.regime_cfg['micro_sentiment']['cvd_intensity_extreme']
        if self._adaptive_on:
            z = self._adaptive_z('cvd', cvd)
            if abs(z) <= self._z_extreme:
                return None
            extreme_threshold = self._z_extreme
        elif abs(cvd) <= extreme_threshold:
            return None
        if not prev:
            return None
        price_delta = abs(curr['price_dynamics']['current_price'] -
                          prev['price_dynamics']['current_price'])
        atr_micro = curr['price_dynamics'].get('atr_micro', 0)
        if atr_micro <= 0:
            return None
        if price_delta >= ABSORPTION_PRICE_STALL_ATR * atr_micro:
            return None

        direction = Direction.BEARISH if cvd > 0 else Direction.BULLISH
        # The driver is the z-score in adaptive mode, the raw ratio otherwise;
        # either way the denominator is derived from the same threshold, so the
        # strength stays comparable across the two modes.
        driver = abs(z) if self._adaptive_on else abs(cvd)
        saturation_denom = max(extreme_threshold * CVD_ABSORPTION_SATURATION, CVD_ABSORPTION_MIN_DENOM)
        strength = min((driver - extreme_threshold) / saturation_denom, 1.0)
        weight = self.signal_weights.get('cvd_absorption')

        return SignalCard(
            signal_id=self._make_id('cvd_absorption', now),
            sub_type='cvd_absorption',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['cvd_absorption'],
            evidence={'cvd_intensity': cvd, 'price_delta': price_delta},
        )

    # ── SIZE: Large Trade / Institutional Activity (#4) ─────────────────

    def _detect_large_trade(self, curr: Dict[str, Any],
                             prev: Optional[Dict[str, Any]],
                             now: datetime) -> Optional[SignalCard]:
        avg_size = curr['sentiment_signals'].get('avg_trade_size', 0.0)
        if avg_size <= 0:
            return None

        thresholds = self.sniper_cfg.get('signal_stack', {}).get('thresholds', {})
        zscore_threshold = thresholds.get('large_trade_zscore', LARGE_TRADE_SATURATION)

        if self._adaptive_on:
            # Same idea, but median/MAD over a time window instead of mean/stdev
            # over a pulse count: a single print spike cannot inflate the scale
            # and mask the next one.
            z_score = self._adaptive_z('avg_trade_size', avg_size)
            zscore_threshold = self._z_entry
        else:
            # Record current value in rolling window
            self._trade_size_window.append(avg_size)
            if len(self._trade_size_window) < MIN_LARGE_TRADE_SAMPLES:
                return None  # need minimum history for meaningful Z-score

            mean = sum(self._trade_size_window) / len(self._trade_size_window)
            variance = sum((x - mean) ** 2 for x in self._trade_size_window) / len(self._trade_size_window)
            std = variance ** 0.5
            if std <= 1e-9:
                return None

            z_score = (avg_size - mean) / std
        if z_score <= zscore_threshold:
            return None

        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        if abs(cvd) <= CVD_NEUTRAL_EPSILON:
            direction = Direction.NEUTRAL
        else:
            direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH

        strength = min(z_score / (zscore_threshold * LARGE_TRADE_SATURATION), 1.0)
        weight = self.signal_weights.get('large_trade', 0.55)

        return SignalCard(
            signal_id=self._make_id('large_trade', now),
            sub_type='large_trade',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['large_trade'],
            evidence={'avg_trade_size': avg_size, 'z_score': z_score,
                      'trade_count': curr['sentiment_signals'].get('trade_count', 0)},
        )

    # ── ENERGY: Volatility Surge (#5) ───────────────────────────────────

    def _detect_volatility_surge(self, curr: Dict[str, Any],
                                  prev: Optional[Dict[str, Any]],
                                  now: datetime) -> Optional[SignalCard]:
        vii = curr['price_dynamics']['volatility_intensity_index']
        vpr = curr['market_regime']['volume_participation_ratio']
        baseline = self.regime_cfg['volatility']['volatility_baseline_ratio']
        volume_threshold = self.sniper_cfg['signal_stack']['thresholds']['volume_participation_threshold']

        if self._adaptive_on:
            # "Unusually volatile AND unusually well participated", both judged
            # against this symbol's own recent spread.  The legacy pair of fixed
            # ratios (vii>1.25, vpr>1.5) is reachable only 2.3-3.8% of the time,
            # and the additional 1.03x one-pulse growth test then removed 95-99%
            # of even those — the detector was effectively dead (0.04-0.15%).
            z_vii = self._adaptive_z('vii', vii)
            z_vpr = self._adaptive_z('vpr', vpr)
            prev_z_vii = self._last_z.get('vii')
            self._last_z['vii'] = z_vii
            if abs(z_vii) <= self._z_entry or abs(z_vpr) <= self._z_entry:
                return None
            # "Surge" still means rising: the z must not have fallen since the
            # previous pulse.  Expressed against its own baseline, a one-pulse
            # wiggle can no longer veto an already-elevated reading.
            if prev_z_vii is not None and z_vii < prev_z_vii:
                return None
            baseline = self._z_entry
            driver = abs(z_vii)
        else:
            if not (vii > baseline and vpr > volume_threshold):
                return None

            if prev:
                prev_vii = prev['price_dynamics']['volatility_intensity_index']
                growth_ratio = self.sniper_cfg['probes'].get('volatility_growth_significance_ratio', 1.03)
                if vii <= prev_vii * growth_ratio:
                    return None
            driver = vii

        cvd = curr['sentiment_signals']['cvd_intensity_ratio']
        if abs(cvd) > 0.05:
            direction = Direction.BULLISH if cvd > 0 else Direction.BEARISH
        elif abs(trend := curr['market_regime'].get('trend_intensity', 0)) > 0.05:
            direction = Direction.BULLISH if trend > 0 else Direction.BEARISH
        else:
            direction = Direction.NEUTRAL  # flat — no directional bias

        strength = min((driver - baseline) / (baseline * VOLATILITY_SATURATION), 1.0)
        weight = self.signal_weights.get('volatility_surge')

        return SignalCard(
            signal_id=self._make_id('volatility_surge', now),
            sub_type='volatility_surge',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['volatility_surge'],
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
            if sf >= prev_sf * SQUEEZE_DECLINE_THRESHOLD:
                return None

        strength = min((threshold - sf) / threshold, 1.0)
        weight = self.signal_weights.get('squeeze')

        return SignalCard(
            signal_id=self._make_id('squeeze', now),
            sub_type='squeeze',
            direction=Direction.NEUTRAL,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['squeeze'],
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
        strength = min(threshold / max(nearest_dist, 0.01) * BOUNDARY_STRENGTH_SCALE, 1.0)
        weight = self.signal_weights.get('boundary_test')

        return SignalCard(
            signal_id=self._make_id('boundary_test', now),
            sub_type='boundary_test',
            direction=direction,
            strength=strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['boundary_test'],
            evidence={'boundary': nearest, 'dist_atr': nearest_dist, 'threshold': threshold},
        )

    # ── STRUCTURAL: Liquidation Hunt (#8) ────────────────────────────────

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
                    strength = min(threshold / max(dist_atr, 0.01) * LIQUIDATION_STRENGTH_SCALE, 1.0)
                    return SignalCard(
                        signal_id=self._make_id('liquidation_hunt', now),
                                sub_type='liquidation_hunt',
                        direction=Direction.BEARISH,
                        strength=strength,
                        weight=self.signal_weights.get('liquidation_hunt'),
                                timestamp=now,
                        decay_half_life_minutes=self._decay['liquidation_hunt'],
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
                    strength = min(threshold / max(dist_atr, 0.01) * LIQUIDATION_STRENGTH_SCALE, 1.0)
                    return SignalCard(
                        signal_id=self._make_id('liquidation_hunt', now),
                                sub_type='liquidation_hunt',
                        direction=Direction.BULLISH,
                        strength=strength,
                        weight=self.signal_weights.get('liquidation_hunt'),
                                timestamp=now,
                        decay_half_life_minutes=self._decay['liquidation_hunt'],
                        evidence={'cluster_price': p, 'dist_atr': dist_atr, 'type': 'short'},
                    )

        return None

    # ── POSITIONING: Unified Positioning Extreme (#9) ───────────────────

    def _detect_positioning_extreme(self, curr: Dict[str, Any],
                                     prev: Optional[Dict[str, Any]],
                                     now: datetime) -> Optional[SignalCard]:
        """Unifies retail_extreme, oi_divergence, and oi_surge into one detector.
        Three independent trigger paths — strongest one wins if multiple fire."""

        best_direction = None
        best_strength = 0.0
        best_evidence: Dict[str, Any] = {}

        # Path 1: LS extreme (retail positioning)
        ls = curr['sentiment_signals'].get('ls_ratio_micro', 1.0)
        cfg = self.regime_cfg['imbalance']
        z_ls = self._adaptive_z('ls', ls)
        if self._adaptive_on:
            # "Crowded on one side", measured against this symbol's own recent
            # positioning rather than an absolute ratio.  The absolute version
            # was unreachable: XAUT's ls never passed 1.07 against a 1.5
            # threshold, BTC's never passed 1.72 against 2.0.
            if z_ls > self._z_entry:
                best_direction = Direction.BEARISH
                best_strength = min(z_ls / (self._z_entry * 2), 1.0)
                best_evidence = {'trigger': 'ls_long_z', 'ls_ratio': ls, 'z': round(z_ls, 2)}
            elif z_ls < -self._z_entry:
                best_direction = Direction.BULLISH
                best_strength = min(-z_ls / (self._z_entry * 2), 1.0)
                best_evidence = {'trigger': 'ls_short_z', 'ls_ratio': ls, 'z': round(z_ls, 2)}
        elif ls > cfg['long_short_imbalance_ratio']:
            strength = min((ls - 1.0) / (cfg['long_short_imbalance_ratio'] * 2), 1.0)
            if strength > best_strength:
                best_direction = Direction.BEARISH
                best_strength = strength
                best_evidence = {'trigger': 'ls_long', 'ls_ratio': ls}
        elif ls < cfg['short_heavy_imbalance_ratio']:
            strength = min((1.0 - ls) / ((1.0 - cfg['short_heavy_imbalance_ratio']) * 2), 1.0)
            if strength > best_strength:
                best_direction = Direction.BULLISH
                best_strength = strength
                best_evidence = {'trigger': 'ls_short', 'ls_ratio': ls}

        # Path 2: Funding extreme
        funding = curr['sentiment_signals'].get('funding_rate', 0.0)
        funding_threshold = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        if self._adaptive_on:
            # Funding is pinned near the exchange's minimum tick for these
            # symbols (observed max 0.0001 against a 0.0005 threshold), so an
            # absolute "extreme" is not a thing that exists.  Relative is.
            f_driver = abs(self._adaptive_z('funding', funding))
            funding_threshold = self._z_extreme
        else:
            f_driver = abs(funding)
        if f_driver > funding_threshold:
            f_direction = Direction.BEARISH if funding > 0 else Direction.BULLISH
            f_strength = min(f_driver / (funding_threshold * FUNDING_SATURATION), 1.0)
            if f_strength > best_strength:
                best_direction = f_direction
                best_strength = f_strength
                best_evidence = {'trigger': 'funding', 'funding_rate': funding}

        # Path 3: OI divergence (OI and price move opposite)
        if prev:
            oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
            price_delta = (curr['price_dynamics']['current_price'] -
                           prev['price_dynamics']['current_price'])
            if self._adaptive_on:
                z_oi = self._adaptive_z('oi_delta', oi_delta)
                oi_scale, oi_floor = abs(z_oi), self._z_entry
                oi_strength = min(oi_scale / (oi_floor * 2.0), 1.0)
                oi_gate = oi_scale > oi_floor
            else:
                # Legacy arithmetic kept verbatim: same gate (0.01, a bare
                # constant) and same saturation (OI_DIVERGENCE_SATURATION).
                oi_strength = min(abs(oi_delta) / OI_DIVERGENCE_SATURATION, 1.0)
                oi_gate = abs(oi_delta) > 0.01
            if abs(oi_delta) > 1e-10 and abs(price_delta) > 1e-10 and oi_gate:
                if (oi_delta > 0 and price_delta < 0) or (oi_delta < 0 and price_delta > 0):
                    oi_dir = Direction.BEARISH if price_delta > 0 else Direction.BULLISH
                    if oi_strength > best_strength:
                        best_direction = oi_dir
                        best_strength = oi_strength
                        best_evidence = {'trigger': 'oi_divergence', 'oi_delta': oi_delta,
                                         'price_delta': price_delta}

        # Path 4: OI surge (OI and price move same direction)
        if prev:
            oi_delta = curr['sentiment_signals'].get('oi_delta_micro', 0.0)
            price_delta = (curr['price_dynamics']['current_price'] -
                           prev['price_dynamics']['current_price'])
            if self._adaptive_on:
                oi_scale2, oi_floor2 = abs(self._adaptive_z('oi_delta', oi_delta)), self._z_extreme
                oi_strength = min((oi_scale2 - oi_floor2) / (oi_floor2 * 2.0), 1.0)
                oi_gate2 = oi_scale2 > oi_floor2
            else:
                # Legacy arithmetic kept verbatim.
                oi_strength = min((abs(oi_delta) - OI_SURGE_MIN_DELTA) / OI_SURGE_SATURATION, 1.0)
                oi_gate2 = abs(oi_delta) > OI_SURGE_MIN_DELTA
            if oi_gate2:
                if (oi_delta > 0 and price_delta > 0) or (oi_delta < 0 and price_delta < 0):
                    oi_dir = Direction.BULLISH if price_delta > 0 else Direction.BEARISH
                    if oi_strength > best_strength:
                        best_direction = oi_dir
                        best_strength = oi_strength
                        best_evidence = {'trigger': 'oi_surge', 'oi_delta': oi_delta,
                                         'price_delta': price_delta}

        if best_direction is None:
            return None

        lock_key = f"POSITIONING_EXTREME_{best_direction.value}"
        if not self._check_state_lock(lock_key, now):
            return None

        weight = self.signal_weights.get('positioning_extreme')

        return SignalCard(
            signal_id=self._make_id('positioning_extreme', now),
            sub_type='positioning_extreme',
            direction=best_direction,
            strength=best_strength,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['positioning_extreme'],
            evidence=best_evidence,
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

        try:
            gate_result, gate_reason = self._run_pre_ai_gate(
                metrics, boosted_signals, dominant_direction, regime
            )
        except Exception as e:
            logger.warning(f"pre-AI gate crashed in reevaluate_with_boost | error={e}")
            return None
        if gate_result == 'FAIL':
            return None

        situation_brief = self._build_situation_brief(
            boosted_signals, confluence_score, dominant_direction
        )
        cooldown_mins = self._get_regime_cooldown(regime)

        # ★ Save fingerprint for cooldown break noise gate
        self._save_fingerprint(metrics)

        return TriggerResult(
            triggered=True,
            confluence_score=confluence_score,
            confluence_direction=dominant_direction,
            signals=boosted_signals,
            active_signals=[s for s in boosted_signals
                           if s.strength >= MIN_STACK_STRENGTH and s.sub_type != 'leader_sync'],
            gate_result=gate_result,
            situation_brief=situation_brief,
            cooldown_minutes=cooldown_mins,
            gate_reason=gate_reason,
            gate_shadow=self._gate_shadow,
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

        boost = min(leader_confluence_score * correlation * LEADER_SYNC_SCALE, LEADER_SYNC_CAP)
        weight = self.signal_weights.get('leader_sync', 0.40)

        return SignalCard(
            signal_id=self._make_id('leader_sync', now),
            sub_type='leader_sync',
            direction=leader_direction,
            strength=boost,
            weight=weight,
            timestamp=now,
            decay_half_life_minutes=self._decay['leader_sync'],
            evidence={'leader_score': leader_confluence_score, 'correlation': correlation},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SIGNAL DIAGNOSTICS — per-pulse compact log of all detector key metrics
    # ═══════════════════════════════════════════════════════════════════════

    def _log_signal_diagnostics(self, metrics: Dict[str, Any],
                                 fresh_signals: List[SignalCard]) -> None:
        """Log a compact per-pulse summary of key decision metrics for all 9
        signal detectors."""
        fired = {s.sub_type: s for s in fresh_signals}
        parts: List[str] = []

        # ── FLOW category ──
        cvd = metrics['sentiment_signals']['cvd_intensity_ratio']
        cvd_thresh = self.regime_cfg['micro_sentiment']['cvd_intensity_threshold']
        parts.append(f"cvd={cvd:+.3f}")

        s = fired.get('cvd_momentum')
        z_cvd = self._adaptive_z('cvd', cvd)
        if s:
            path = s.evidence.get('trigger_path', '?')
            parts.append(f"cvd_momentum=F:{s.strength:.2f}({path})")
        elif self._adaptive_on:
            # Report the threshold actually in force, not the legacy constant.
            parts.append(f"cvd_momentum=R:|z|={abs(z_cvd):.2f}<={self._z_entry}")
        else:
            if abs(cvd) <= cvd_thresh:
                parts.append(f"cvd_momentum=R:|cvd|={abs(cvd):.3f}<={cvd_thresh}")
            else:
                parts.append(f"cvd_momentum=R:no_growth(|cvd|={abs(cvd):.3f}>{cvd_thresh})")

        s = fired.get('cvd_divergence')
        parts.append(f"cvd_divergence={'F:'+str(round(s.strength,2)) if s else 'R:'+self._cvd_div_reason}")
        s = fired.get('cvd_absorption')
        parts.append(f"cvd_absorption={'F:'+str(round(s.strength,2)) if s else f'R:|cvd|<=extreme'}")

        # ── SIZE category ──
        avg_size = metrics['sentiment_signals'].get('avg_trade_size', 0.0)
        trade_n = metrics['sentiment_signals'].get('trade_count', 0)
        z_thresh = self._signal_cfg('thresholds', 'large_trade_zscore', default=2.0)
        s = fired.get('large_trade')
        if s:
            z = s.evidence.get('z_score', 0.0)
            parts.append(f"trade_sz={avg_size:.4f}/n={trade_n} | large_trade=F:{s.strength:.2f}(z={z:.1f})")
        elif self._adaptive_on:
            # The legacy deque is deliberately not fed in adaptive mode, so it
            # must not be used to describe readiness either.
            win = self._adaptive.window('avg_trade_size')
            z = self._adaptive_z('avg_trade_size', avg_size)
            mark = (f"R:z={z:.2f}<={self._z_entry}" if win.ready
                    else f"R:warmup({win.count}/{win.min_samples})")
            parts.append(f"trade_sz={avg_size:.4f}/n={trade_n} | large_trade={mark}")
        elif len(self._trade_size_window) < MIN_LARGE_TRADE_SAMPLES:
            parts.append(f"trade_sz={avg_size:.4f}/n={trade_n} | large_trade=R:warmup({len(self._trade_size_window)}/{MIN_LARGE_TRADE_SAMPLES})")
        else:
            mean = sum(self._trade_size_window) / len(self._trade_size_window)
            std = (sum((x - mean) ** 2 for x in self._trade_size_window) / len(self._trade_size_window)) ** 0.5
            z = (avg_size - mean) / std if std > 1e-9 else 0.0
            parts.append(f"trade_sz={avg_size:.4f}/n={trade_n} | large_trade=R:z={z:.1f}<={z_thresh}")

        # ── ENERGY category ──
        vii = metrics['price_dynamics']['volatility_intensity_index']
        vpr = metrics['market_regime']['volume_participation_ratio']
        parts.append(f"vii={vii:.2f},vpr={vpr:.2f}")

        s = fired.get('volatility_surge')
        vol_base = self.regime_cfg['volatility']['volatility_baseline_ratio']
        volume_threshold = self.sniper_cfg['signal_stack']['thresholds']['volume_participation_threshold']
        if s:
            parts.append(f"vol_surge=F:{round(s.strength, 2)}")
        elif self._adaptive_on:
            parts.append(f"vol_surge=R:z_vii={self._adaptive_z('vii', vii):.2f}|"
                         f"z_vpr={self._adaptive_z('vpr', vpr):.2f}<={self._z_entry}")
        else:
            parts.append(f"vol_surge=R:vii<={vol_base}|vpr<={volume_threshold}")

        sf = metrics['market_regime']['squeeze_factor']
        sq_thresh = (self.regime_cfg['volatility']['squeeze_threshold'] *
                     self.sniper_cfg['probes']['squeeze_trigger_multiplier'])
        s = fired.get('squeeze')
        parts.append(f"squeeze={'F:'+str(round(s.strength,2)) if s else f'R:sf={sf:.3f}>={sq_thresh:.3f}'}")

        # ── STRUCTURAL category ──
        price = metrics['price_dynamics']['current_price']
        atr = metrics['price_dynamics'].get('atr_macro', 0)
        topo = metrics['volume_profile']
        parts.append(f"price={price:.1f},atr={atr:.2f}")

        s = fired.get('boundary_test')
        if atr > 0:
            dist_vh = abs(price - topo['vah']) / atr
            dist_val = abs(price - topo['val']) / atr
            prox_thresh = self.sniper_cfg['proximity']['vah_val_atr']
            parts.append(f"boundary_test={'F:'+str(round(s.strength,2)) if s else f'R:dist_vh={dist_vh:.1f},dist_val={dist_val:.1f}>={prox_thresh}'}")
        else:
            parts.append("boundary_test=R:atr=0")

        s = fired.get('liquidation_hunt')
        parts.append(f"liq_hunt={'F:'+str(round(s.strength,2)) if s else 'R:no-cluster-in-range'}")

        # ── POSITIONING category ──
        ls = metrics['sentiment_signals'].get('ls_ratio_micro', 1.0)
        funding = metrics['sentiment_signals'].get('funding_rate', 0.0)
        oi_delta = metrics['sentiment_signals'].get('oi_delta_micro', 0.0)
        parts.append(f"ls={ls:.2f},fund={funding:.4f},oi_d={oi_delta:.4f}")

        s = fired.get('positioning_extreme')
        ls_imb = self.regime_cfg['imbalance']['long_short_imbalance_ratio']
        ls_short = self.regime_cfg['imbalance']['short_heavy_imbalance_ratio']
        fund_ext = self.regime_cfg['micro_sentiment']['funding_extreme_threshold']
        if s:
            parts.append(f"pos_ext=F:{round(s.strength, 2)}")
        elif self._adaptive_on:
            parts.append(f"pos_ext=R:z_ls={self._adaptive_z('ls', ls):.2f}|"
                         f"z_fund={self._adaptive_z('funding', funding):.2f}|"
                         f"z_oi={self._adaptive_z('oi_delta', oi_delta):.2f}"
                         f" (entry {self._z_entry}/extreme {self._z_extreme})")
        else:
            parts.append(f"pos_ext=R:ls<={ls_imb}&ls>={ls_short}&|fund|<={fund_ext}&oi<0.01")

        # ── PROVENANCE ──
        # How many *independent* information sources are behind the dominant
        # direction.  Ten detectors that all read the same order-flow number are
        # one observation; this makes that visible per pulse.
        active = [s for s in fresh_signals
                  if s.direction != Direction.NEUTRAL and s.strength >= MIN_STACK_STRENGTH]
        src = sorted({s.source for s in active})
        parts.append(f"sources={len(src)}[{','.join(src) if src else '-'}]")

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
        2. Detect all 9 direct signal types
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

        # 0b. Buffer this pulse so cvd_divergence can compare one candle apart,
        #     then fold the pulse into the adaptive baselines.
        self._record_cvd_sample(current_metrics, now)
        self._record_adaptive_samples(current_metrics, now)

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
            cooldown_break = self._check_cooldown_break(fresh_signals)

            # ★ Structural fingerprint gate: if structure hasn't changed,
            #   don't allow cooldown break — prevents re-triggering on the
            #   same market conditions.
            if cooldown_break:
                unchanged, delta_summary = self._structure_is_unchanged(current_metrics)
                if unchanged:
                    logger.info(
                        "[%s] cooldown NOT broken: structure unchanged (%s)",
                        self.symbol, delta_summary,
                    )
                    cooldown_break = False
                else:
                    logger.info("[%s] cooldown break: signal surge", self.symbol)

        # 5. Compute confluence
        effective_cooldown = cooldown_active and not cooldown_break
        self.cooldown_active = effective_cooldown
        confluence_score, dominant_direction, should_trigger = self.engine.evaluate(
            all_signals, regime, is_cooldown_active=effective_cooldown
        )
        effective_threshold = self.engine.effective_threshold

        # Why this pulse did (not) reach a session.  Surfaced through TriggerResult
        # into .sniper_pulse.json so the dashboard/MCP can answer "why didn't it
        # wake?" without re-parsing the log.
        gate_result = "SKIPPED"
        gate_reason = f"BELOW_THRESHOLD (conf={confluence_score:.2f} < thr={effective_threshold:.3f})"

        # ★ Cooldown suppression is otherwise invisible: the engine folds it into
        #   should_trigger, so a would-be wake that never fired leaves no trace.
        if (effective_cooldown and not should_trigger
                and confluence_score >= effective_threshold):
            logger.info(
                "[%s] COOLDOWN BLOCK | %s | conf=%.2f >= thr=%.3f | dir=%s | regime=%s",
                self.symbol, cooldown_reason, confluence_score,
                effective_threshold, dominant_direction.value, regime,
            )
            gate_reason = cooldown_reason

        # 6. Pre-AI Gate
        if should_trigger:
            try:
                gate_result, gate_reason = self._run_pre_ai_gate(
                    current_metrics, all_signals, dominant_direction, regime
                )
            except Exception as e:
                logger.warning(f"pre-AI gate crashed | error={e}")
                gate_result, gate_reason = "FAIL", f"gate_crashed:{type(e).__name__}"
            if gate_result == "FAIL":
                logger.info(
                    "[%s] PRE-AI GATE FAIL | %s | conf=%.2f | dir=%s | regime=%s | fresh=%d",
                    self.symbol, gate_reason, confluence_score,
                    dominant_direction.value, regime, len(fresh_signals),
                )
                should_trigger = False

        # 7. Build situation brief
        situation_brief = None
        if should_trigger:
            situation_brief = self._build_situation_brief(
                all_signals, confluence_score, dominant_direction
            )
            # ★ Snapshot structure at trigger time for cooldown break noise gate
            self._save_fingerprint(current_metrics)

        # 8. Cooldown for this trigger
        cooldown_mins = self._get_regime_cooldown(regime)

        result = TriggerResult(
            triggered=should_trigger,
            confluence_score=confluence_score,
            confluence_direction=dominant_direction,
            signals=all_signals,
            active_signals=[s for s in fresh_signals if s.strength >= MIN_STACK_STRENGTH],
            gate_result=gate_result,
            situation_brief=situation_brief,
            cooldown_minutes=cooldown_mins,
            gate_reason=gate_reason,
            gate_shadow=self._gate_shadow,
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
