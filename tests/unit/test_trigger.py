"""Tests for Sniper Trigger — SignalCard, SignalMemory, ConfluenceEngine."""
import math
from datetime import datetime, timezone, timedelta
import pytest
from src.sniper.trigger import (
    SignalCard, SignalMemory, ConfluenceEngine, Direction, SniperTrigger,
    SIGNAL_SOURCES, DEFAULT_SIGNAL_SOURCE,
)


# ═══════════════════════════════════════════════════════════════════════════
# SignalCard
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalCard:

    def _card(self, strength=0.5, weight=0.8, decay=10.0):
        return SignalCard(
            signal_id="test_1", sub_type="test",
            direction=Direction.BULLISH, strength=strength, weight=weight, timestamp=datetime.now(timezone.utc),
            decay_half_life_minutes=decay,
        )

    def test_weighted_score_normal(self):
        c = self._card(strength=0.5, weight=0.8)
        assert c.weighted_score == pytest.approx(0.4)

    def test_weighted_score_zero_strength(self):
        c = self._card(strength=0.0, weight=0.8)
        assert c.weighted_score == pytest.approx(0.0)

    def test_weighted_score_nan_strength(self):
        c = self._card(strength=math.nan, weight=0.8)
        assert c.weighted_score == pytest.approx(0.0)

    def test_weighted_score_inf_weight(self):
        c = self._card(strength=0.5, weight=math.inf)
        assert c.weighted_score == pytest.approx(0.0)

    def test_decayed_strength_no_elapsed(self):
        c = self._card(strength=0.8, decay=10.0)
        # Same timestamp → no decay
        result = c.decayed_strength(c.timestamp)
        assert result == pytest.approx(0.8)

    def test_decayed_strength_half_life(self):
        c = self._card(strength=1.0, decay=10.0)
        # After 10 minutes → strength halved
        later = c.timestamp + timedelta(minutes=10)
        result = c.decayed_strength(later)
        assert result == pytest.approx(0.5)

    def test_decayed_strength_zero_half_life(self):
        c = self._card(strength=1.0, decay=0.0)
        later = c.timestamp + timedelta(minutes=5)
        # decay_half_life_minutes floors to 0.01
        result = c.decayed_strength(later)
        assert result > 0.0
        assert result < 1.0

# ═══════════════════════════════════════════════════════════════════════════
# SignalMemory
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalMemory:

    def _card(self, sid="flow.cvd_1", sub_type="cvd_divergence", strength=0.5, ts=None):
        return SignalCard(
            signal_id=sid, sub_type=sub_type,
            direction=Direction.BULLISH, strength=strength, weight=0.8, timestamp=ts or datetime.now(timezone.utc),
            decay_half_life_minutes=10.0,
        )

    def test_ingest_empty(self):
        mem = SignalMemory()
        now = datetime.now(timezone.utc)
        result = mem.ingest([], now)
        assert result == []

    def test_ingest_new_signal(self):
        mem = SignalMemory()
        now = datetime.now(timezone.utc)
        cards = [self._card()]
        result = mem.ingest(cards, now)
        assert len(result) == 1
        assert result[0].signal_id == "flow.cvd_1"

    def test_ingest_expired_signal_purged(self):
        mem = SignalMemory()
        old_ts = datetime.now(timezone.utc) - timedelta(hours=24)
        cards = [self._card(strength=0.1, ts=old_ts)]
        mem.ingest(cards, old_ts)  # stored at old_ts

        now = datetime.now(timezone.utc)
        # strength already decayed to < 0.05, should be purged
        result = mem.ingest([], now)
        assert len(result) == 0

    def test_ingest_new_replaces_old_same_subtype(self):
        mem = SignalMemory()
        now = datetime.now(timezone.utc)
        old_card = self._card(sub_type="cvd_divergence", strength=0.3, ts=now)
        mem.ingest([old_card], now)

        new_card = self._card(sub_type="cvd_divergence", strength=0.9, ts=now)
        result = mem.ingest([new_card], now)
        # Only the new one should survive (same sub_type)
        assert len(result) == 1
        assert result[0].strength == pytest.approx(0.9)


# ═══════════════════════════════════════════════════════════════════════════
# ConfluenceEngine
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    return ConfluenceEngine({
        'trigger_threshold': 0.35,
        'emergency_threshold': 0.85,
        'regime_modifiers': {'trending': 0.85, 'ranging': 1.15, 'squeeze': 0.70, 'chaos': 1.50},
        'weights': {},
    })


class TestConfluenceEngine:

    def _card(self, direction=Direction.BULLISH, strength=0.5, weight=0.8):
        return SignalCard(
            signal_id="t", sub_type="test",
            direction=direction, strength=strength, weight=weight, timestamp=datetime.now(timezone.utc),
            decay_half_life_minutes=10.0,
        )

    def test_no_signals(self, engine):
        score, direction, trigger = engine.evaluate([], "ranging")
        assert score == pytest.approx(0.0)
        assert trigger is False

    def test_single_bullish_strong(self, engine):
        signals = [self._card(Direction.BULLISH, strength=0.9, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "trending")
        assert direction == Direction.BULLISH
        assert trigger is True

    def test_single_weak_below_threshold(self, engine):
        signals = [self._card(Direction.BULLISH, strength=0.1, weight=0.3)]
        score, direction, trigger = engine.evaluate(signals, "ranging")
        # threshold = 0.35 * 1.15 = 0.4025
        assert trigger is False

    def test_regime_modifier_chaos_raises_threshold(self, engine):
        """Chaos modifier (1.50) raises effective threshold to 0.525."""
        signals = [self._card(Direction.BULLISH, strength=0.4, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "chaos")
        # effective_threshold = 0.35 * 1.50 = 0.525, score = 0.4 < 0.525
        assert trigger is False

    def test_regime_modifier_squeeze_lowers_threshold(self, engine):
        """Squeeze modifier (0.70) lowers effective threshold to 0.245."""
        signals = [self._card(Direction.BULLISH, strength=0.3, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "squeeze")
        assert trigger is True

    def test_emergency_override_triggers_during_cooldown(self, engine):
        signals = [self._card(Direction.BULLISH, strength=0.9, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "ranging", is_cooldown_active=True)
        assert trigger is True  # emergency: strength=0.9 >= 0.85

    def test_cooldown_blocks_non_emergency(self, engine):
        signals = [self._card(Direction.BULLISH, strength=0.5, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "ranging", is_cooldown_active=True)
        assert trigger is False  # strength=0.5 < 0.85 emergency

    def test_neutral_signals_dont_trigger_emergency(self, engine):
        """NEUTRAL direction signals should not count as emergency override."""
        signals = [self._card(Direction.NEUTRAL, strength=0.9, weight=1.0)]
        score, direction, trigger = engine.evaluate(signals, "ranging")
        assert trigger is False

    def test_bullish_wins_over_bearish(self, engine):
        signals = [
            self._card(Direction.BULLISH, strength=0.6, weight=1.0),
            self._card(Direction.BEARISH, strength=0.3, weight=1.0),
        ]
        score, direction, trigger = engine.evaluate(signals, "trending")
        assert direction == Direction.BULLISH

    def test_directional_score_below_min_strength_ignored(self, engine):
        """strength < 0.15 should be excluded from stacking."""
        signals = [
            self._card(Direction.BULLISH, strength=0.05, weight=1.0),
        ]
        score, direction, trigger = engine.evaluate(signals, "trending")
        # No matching signal (below min_strength_for_stack=0.15)
        assert score == pytest.approx(0.0)
        assert trigger is False

    def test_nan_score_returns_zero_trigger(self, engine):
        """NaN confluence returns 0.0 score and False trigger."""
        signals = [self._card(Direction.BULLISH, strength=math.nan, weight=math.nan)]
        score, direction, trigger = engine.evaluate(signals, "ranging")
        assert score == pytest.approx(0.0)
        assert trigger is False


def test_sniper_trigger_initialization_with_symbol_override():
    """SniperTrigger initialized with symbol alone should resolve per-symbol overrides."""
    from src.sniper.trigger import SniperTrigger
    trigger_btc = SniperTrigger(symbol="BTCUSDT")
    # BTC overrides trigger_threshold to 0.36 and cvd_divergence_candle_delta to 0.16
    thresholds = trigger_btc.sniper_cfg.get("signal_stack", {}).get("thresholds", {})
    assert thresholds.get("cvd_divergence_candle_delta") == 0.16
    assert trigger_btc.sniper_cfg.get("signal_stack", {}).get("trigger_threshold") == 0.36



# ═══════════════════════════════════════════════════════════════════════════
# Pre-AI Gate — min_active_trend / min_active_non_trend
# ═══════════════════════════════════════════════════════════════════════════

def _make_trigger(min_active_trend=None, min_active_non_trend=None, **gate_extra):
    gate = dict(gate_extra)
    if min_active_trend is not None:
        gate['min_active_trend'] = min_active_trend
    if min_active_non_trend is not None:
        gate['min_active_non_trend'] = min_active_non_trend
    strat = {
        'regime_parameters': {
            'trend': {'trend_intensity_strong': 0.6},
            'micro_sentiment': {'cvd_intensity_threshold': 0.2},
        },
        'analysis_window': {'macro_context': {'time_interval': '1h'}},
    }
    glob = {
        'sniper': {
            'signal_stack': {
                'trigger_threshold': 0.34,
                'weights': {},
                'decay': {
                    'cvd_momentum': 15, 'cvd_divergence': 6, 'cvd_absorption': 15,
                    'large_trade': 10, 'volatility_surge': 20, 'squeeze': 20,
                    'boundary_test': 10, 'liquidation_hunt': 10,
                    'positioning_extreme': 40, 'leader_sync': 8,
                },
                'gate': gate,
            },
        },
    }
    return SniperTrigger(strategy_cfg=strat, global_cfg=glob)


def _gate_card(sub_type='large_trade', direction=Direction.BULLISH, strength=0.6):
    return SignalCard(
        signal_id=f'{sub_type}_1', sub_type=sub_type, direction=direction,
        strength=strength, weight=0.55, timestamp=datetime.now(timezone.utc),
        decay_half_life_minutes=10.0,
    )


def _gate_metrics(trend=0.5, cvd=0.1):
    return {
        'market_regime': {'trend_intensity': trend},
        'sentiment_signals': {'cvd_intensity_ratio': cvd},
    }


class TestPreAIGate:

    def test_trending_min_active_trend_1_passes_single_signal(self):
        t = _make_trigger(min_active_trend=1)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), [_gate_card()], Direction.BULLISH, 'trending')
        assert result == 'PASS'

    def test_trending_min_active_trend_2_blocks_single_signal(self):
        t = _make_trigger(min_active_trend=2)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), [_gate_card()], Direction.BULLISH, 'trending')
        assert result == 'FAIL'
        assert 'MIN_ACTIVE_TREND' in reason

    def test_trending_min_active_trend_2_passes_two_signals(self):
        t = _make_trigger(min_active_trend=2)
        sigs = [_gate_card('large_trade'), _gate_card('cvd_momentum')]
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), sigs, Direction.BULLISH, 'trending')
        assert result == 'PASS'

    def test_trending_ignores_min_active_non_trend(self):
        # min_active_trend unset (0) → trending not gated even though non_trend=2
        t = _make_trigger(min_active_non_trend=2)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), [_gate_card()], Direction.BULLISH, 'trending')
        assert result == 'PASS'

    def test_ranging_min_active_non_trend_2_blocks_single_signal(self):
        t = _make_trigger(min_active_non_trend=2)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), [_gate_card()], Direction.BULLISH, 'ranging')
        assert result == 'FAIL'
        assert 'MIN_ACTIVE_SIGNALS' in reason

    def test_ranging_min_active_non_trend_2_passes_two_signals(self):
        t = _make_trigger(min_active_non_trend=2)
        sigs = [_gate_card('large_trade'), _gate_card('cvd_momentum')]
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), sigs, Direction.BULLISH, 'ranging')
        assert result == 'PASS'

    def test_ranging_ignores_min_active_trend(self):
        # min_active_non_trend unset (0) → ranging not gated even though trend=2
        t = _make_trigger(min_active_trend=2)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), [_gate_card()], Direction.BULLISH, 'ranging')
        assert result == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════
# Direction-provenance gate (require_independent_direction / shadow mode)
# See docs/sniper_gate_review_and_plan_20260917.md
# ═══════════════════════════════════════════════════════════════════════════

def _cvd_stack():
    """3 same-direction signals whose direction all derives from sign(cvd)."""
    return [_gate_card('cvd_momentum'), _gate_card('large_trade'),
            _gate_card('volatility_surge')]


class TestDirectionProvenanceGate:

    def test_disabled_by_default_passes_pure_cvd_stack(self):
        t = _make_trigger(min_active_non_trend=3)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), _cvd_stack(), Direction.BULLISH, 'ranging')
        assert result == 'PASS'

    def test_shadow_mode_logs_but_does_not_block(self, caplog):
        t = _make_trigger(min_active_non_trend=3,
                          shadow_require_independent_direction=True,
                          require_independent_direction=False)
        with caplog.at_level('INFO', logger='src.sniper.trigger'):
            result, reason = t._run_pre_ai_gate(
                _gate_metrics(), _cvd_stack(), Direction.BULLISH, 'ranging')
        assert result == 'PASS'
        assert any('GATE SHADOW' in r.message for r in caplog.records)

    def test_enabled_blocks_pure_cvd_stack(self):
        t = _make_trigger(min_active_non_trend=3,
                          require_independent_direction=True)
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), _cvd_stack(), Direction.BULLISH, 'ranging')
        assert result == 'FAIL'
        assert 'MIN_ACTIVE_INDEPENDENT' in reason

    def test_enabled_passes_when_an_independent_source_agrees(self):
        # cvd_divergence derives direction from price_delta/cvd_delta, not sign(cvd)
        t = _make_trigger(min_active_non_trend=3,
                          require_independent_direction=True)
        sigs = [_gate_card('cvd_momentum'), _gate_card('large_trade'),
                _gate_card('cvd_divergence')]
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), sigs, Direction.BULLISH, 'ranging')
        assert result == 'PASS'

    def test_count_gate_still_wins_first(self):
        # 2 signals < min 3 → the count gate fails before provenance is examined
        t = _make_trigger(min_active_non_trend=3,
                          require_independent_direction=True)
        sigs = [_gate_card('cvd_momentum'), _gate_card('large_trade')]
        result, reason = t._run_pre_ai_gate(
            _gate_metrics(), sigs, Direction.BULLISH, 'ranging')
        assert result == 'FAIL'
        assert 'MIN_ACTIVE_SIGNALS' in reason


# ═══════════════════════════════════════════════════════════════════════════
# gate_result / gate_reason — why a pulse did (not) wake
# Contract consumed by run_sniper._write_pulse -> .sniper_pulse.json -> MCP.
# ═══════════════════════════════════════════════════════════════════════════

_DECAY = {'cvd_momentum': 15, 'cvd_divergence': 6, 'cvd_absorption': 15, 'large_trade': 10,
          'volatility_surge': 20, 'squeeze': 20, 'boundary_test': 10, 'liquidation_hunt': 10,
          'positioning_extreme': 40, 'leader_sync': 8}
_WEIGHTS = {'cvd_momentum': 0.65, 'cvd_divergence': 0.70, 'cvd_absorption': 0.50,
            'large_trade': 0.55, 'volatility_surge': 0.55, 'squeeze': 0.75,
            'boundary_test': 0.50, 'liquidation_hunt': 0.60, 'positioning_extreme': 0.50}


def _full_trigger(gate):
    """A trigger with enough config for the full evaluate() path (all detectors)."""
    strat = {
        'regime_parameters': {
            'trend': {'trend_intensity_strong': 0.6, 'trend_intensity_threshold': 0.25},
            'volatility': {'squeeze_threshold': 1.0, 'volatility_extreme_ratio': 2.2,
                           'volatility_baseline_ratio': 1.25},
            'micro_sentiment': {'cvd_intensity_threshold': 0.20, 'cvd_intensity_extreme': 0.36,
                                'funding_extreme_threshold': 0.0005},
            'imbalance': {'long_short_imbalance_ratio': 1.5, 'short_heavy_imbalance_ratio': 0.6},
            'volume': {'min_volume_participation_ratio': 1.0},
        },
        'analysis_window': {'macro_context': {'time_interval': '1h'},
                            'micro_context': {'time_interval': '15m'}},
    }
    sniper = {
        'signal_stack': {
            'trigger_threshold': 0.34, 'emergency_threshold': 0.80,
            'regime_modifiers': {'trending': 0.85, 'ranging': 1.0, 'squeeze': 0.75, 'chaos': 1.5},
            'weights': _WEIGHTS, 'decay': _DECAY,
            'cooldown': {'regime_base_minutes': {'trending': 20, 'ranging': 40,
                                                 'squeeze': 20, 'chaos': 60},
                         'neutral_multiplier': 0.8, 'failure_cooldown_minutes': 3},
            'thresholds': {'cvd_divergence_candle_delta': 0.12, 'cvd_extreme_threshold': 0.24,
                           'large_trade_zscore': 1.6, 'volume_participation_threshold': 1.5},
            'gate': gate,
        },
        'probes': {'cvd_growth_significance_ratio': 1.0, 'squeeze_trigger_multiplier': 1.3,
                   'volatility_growth_significance_ratio': 1.03},
        'proximity': {'vah_val_atr': 0.7, 'liq_atr': 0.5},
    }
    return SniperTrigger(strategy_cfg=strat, global_cfg={'sniper': sniper})


def _full_metrics(cvd=0.60, price=4400.0):
    return {
        'market_regime': {'trend_intensity': 0.0, 'volume_participation_ratio': 2.0,
                          'squeeze_factor': 1.5},
        'sentiment_signals': {'cvd_intensity_ratio': cvd, 'avg_trade_size': 0.05,
                              'trade_count': 1000, 'ls_ratio_micro': 1.0, 'funding_rate': 0.0,
                              'oi_delta_micro': 0.0, 'liquidation_clusters': {}},
        'price_dynamics': {'volatility_intensity_index': 1.0, 'current_price': price,
                           'atr_macro': 20.0, 'atr_micro': 20.0},
        'volume_profile': {'vah': price + 100.0, 'val': price - 100.0, 'poc': price},
    }


class TestGateReasonContract:

    GATE = {'min_active_non_trend': 3, 'min_active_trend': 1}

    def test_gate_fail_reason_is_surfaced(self):
        r = _full_trigger(self.GATE).evaluate(_full_metrics(cvd=0.60), None)
        assert r.triggered is False
        assert r.gate_result == 'FAIL'
        assert 'MIN_ACTIVE_SIGNALS' in r.gate_reason

    def test_below_threshold_is_skipped_not_failed(self):
        r = _full_trigger(self.GATE).evaluate(_full_metrics(cvd=0.05), None)
        assert r.gate_result == 'SKIPPED'
        assert 'BELOW_THRESHOLD' in r.gate_reason

    def test_cooldown_block_reason_is_surfaced(self):
        t = _full_trigger(self.GATE)
        t.last_trigger_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        t._last_trigger_type = 'TRADED'
        # cvd 0.384 -> strength 0.60 (below the 0.80 emergency bar), conf 0.39 >= 0.34
        r = t.evaluate(_full_metrics(cvd=0.384), None)
        assert r.triggered is False
        assert r.gate_result == 'SKIPPED'
        assert 'COOLDOWN' in r.gate_reason

    def test_gate_reason_defaults_to_empty(self):
        # positional/keyword construction in other call sites must keep working
        from src.sniper.trigger import TriggerResult, Direction
        r = TriggerResult(triggered=False, confluence_score=0.0,
                          confluence_direction=Direction.NEUTRAL, signals=[],
                          active_signals=[], gate_result='PASS', situation_brief=None,
                          cooldown_minutes=40.0)
        assert r.gate_reason == ''


# ═══════════════════════════════════════════════════════════════════════════
# reset_state — invoked by the daemon after a long gap (host suspend / outage)
# ═══════════════════════════════════════════════════════════════════════════

class TestResetState:

    def _dirty_trigger(self):
        t = _make_trigger(min_active_non_trend=3, min_active_trend=1)
        t.memory.active_signals = {'cvd_momentum': _gate_card('cvd_momentum')}
        t.last_trigger_time = datetime.now(timezone.utc)
        t.last_trigger_score = 0.9
        t._last_trigger_type = 'TRADED'
        t.cooldown_active = True
        t.state_locks['BOUNDARY_VAH'] = (datetime.now(timezone.utc), 1.0)
        t._fingerprint = 'stale'
        t._cvd_history.append((datetime.now(timezone.utc), 0.42, 4400.0))
        t._cvd_div_reason = 'F:0.50'
        return t

    def test_clears_signal_memory(self):
        t = self._dirty_trigger()
        t.reset_state()
        assert t.memory.active_signals == {}

    def test_clears_cooldown(self):
        t = self._dirty_trigger()
        t.reset_state()
        assert t.cooldown_active is False
        assert t.last_trigger_time is None
        assert t.last_trigger_score is None
        assert t._last_trigger_type is None

    def test_clears_locks_and_fingerprint(self):
        t = self._dirty_trigger()
        t.reset_state()
        assert t.state_locks == {}
        assert t._fingerprint is None

    def test_clears_cvd_history(self):
        """A candle-lagged comparison across a suspend gap is meaningless, so the
        buffer must go with the rest of the cross-pulse state."""
        t = self._dirty_trigger()
        t.reset_state()
        assert list(t._cvd_history) == []
        assert t._cvd_div_reason == "warmup"

    def test_leaves_config_untouched(self):
        t = self._dirty_trigger()
        weights_before = dict(t.signal_weights)
        t.reset_state()
        assert t.signal_weights == weights_before
        assert t.sniper_cfg['signal_stack']['gate']['min_active_non_trend'] == 3


# ═══════════════════════════════════════════════════════════════════════════
# cvd_divergence — candle-lagged comparison
# ═══════════════════════════════════════════════════════════════════════════
#
# Regression: the detector used to difference consecutive pulses (2 min apart),
# but cvd_intensity_ratio is net taker flow over the last four 15-minute
# candles, so it steps whenever a candle closes — a full candle leaves the
# window and an empty one enters, shrinking the denominator. Over
# 2026-09-18→10-05 that put 70% (XAUT) / 90% (BTC) of its fires in the first
# two minutes after a candle close, i.e. 13% of the time. Comparing samples one
# candle apart cancels the rollover (measured boundary bias 3.7x → 1.04x).

class TestCvdDivergenceCandleLag:

    LAG = 15.0

    def _trigger(self):
        t = _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1})
        t._cvd_lag_minutes = self.LAG
        t._cvd_history.clear()
        return t

    def _with_history(self, entries):
        """entries: list of (minutes_ago, cvd, price)."""
        t = self._trigger()
        now = datetime.now(timezone.utc)
        for mins, cvd, price in entries:
            t._cvd_history.append((now - timedelta(minutes=mins), cvd, price))
        return t, now

    # ── reference lookup ───────────────────────────────────────────────────

    def test_warmup_has_no_reference(self):
        t, now = self._with_history([(2.0, 0.20, 4400.0)])
        assert t._cvd_reference(now) is None

    def test_picks_the_sample_one_candle_back(self):
        t, now = self._with_history([(2.0, 0.20, 4400.0), (15.0, 0.35, 4410.0)])
        ref = t._cvd_reference(now)
        assert ref is not None
        assert ref[1] == pytest.approx(0.35)
        assert ref[2] == pytest.approx(4410.0)

    def test_rejects_a_sample_outside_the_tolerance(self):
        """~19 min is not "one candle back"; better dark than comparing to noise."""
        t, now = self._with_history([(19.0, 0.35, 4410.0)])
        assert t._cvd_reference(now) is None

    def test_prefers_the_closer_of_two_candidates(self):
        t, now = self._with_history([(13.5, 0.20, 4400.0), (16.0, 0.35, 4410.0)])
        ref = t._cvd_reference(now)
        assert ref is not None and ref[1] == pytest.approx(0.35)

    # ── the failure mode this fixes ────────────────────────────────────────

    def test_rollover_jump_between_pulses_does_not_fire(self):
        """A violent 2-minute CVD swing that is only the window rollover.

        The old detector saw |ΔCVD| = +0.32 against a 0.12 threshold and fired;
        measured candle-to-candle the change is +0.02, so nothing fires.
        """
        t, now = self._with_history([(2.0, 0.10, 4400.0), (15.0, 0.40, 4400.0)])
        card = t._detect_cvd_divergence(_full_metrics(cvd=0.42, price=4390.0), None, now)
        assert card is None
        assert "|dCVD|" in t._cvd_div_reason

    def test_genuine_candle_drift_fires(self):
        t, now = self._with_history([(15.0, 0.10, 4400.0)])
        card = t._detect_cvd_divergence(_full_metrics(cvd=0.40, price=4390.0), None, now)
        assert card is not None
        assert card.sub_type == 'cvd_divergence'
        assert card.direction == Direction.BULLISH  # price down, flow up
        assert card.evidence['ref_age_minutes'] == pytest.approx(15.0, abs=0.1)

    def test_agreement_is_not_a_divergence(self):
        t, now = self._with_history([(15.0, 0.10, 4400.0)])
        card = t._detect_cvd_divergence(_full_metrics(cvd=0.40, price=4410.0), None, now)
        assert card is None
        assert "no divergence" in t._cvd_div_reason

    def test_stays_dark_without_a_reference(self):
        t, now = self._with_history([(2.0, 0.10, 4400.0)])
        card = t._detect_cvd_divergence(_full_metrics(cvd=0.40, price=4390.0), None, now)
        assert card is None
        assert t._cvd_div_reason.startswith("warmup")

    # ── pulse buffering ────────────────────────────────────────────────────

    def test_evaluate_records_each_pulse(self):
        t = _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1})
        t._cvd_history.clear()
        t.evaluate(_full_metrics(cvd=0.20, price=4400.0), None)
        assert len(t._cvd_history) == 1
        assert t._cvd_history[0][1] == pytest.approx(0.20)
        t.evaluate(_full_metrics(cvd=0.22, price=4403.0), None)
        assert len(t._cvd_history) == 2

    def test_evaluate_skips_pulses_without_cvd_or_price(self):
        t = _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1})
        t._cvd_history.clear()
        metrics = _full_metrics(cvd=0.20, price=4400.0)
        metrics['price_dynamics']['current_price'] = 0.0
        t.evaluate(metrics, None)
        assert len(t._cvd_history) == 0

    def test_lag_is_derived_from_the_micro_candle(self):
        t = _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1})
        assert t._cvd_lag_minutes == pytest.approx(15.0)


# ═══════════════════════════════════════════════════════════════════════════
# Provenance — signals sharing a source are not independent confirmations
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalSources:

    def test_source_is_derived_from_sub_type(self):
        c = _gate_card(sub_type='cvd_momentum')
        assert c.source == 'flow'

    def test_every_registered_detector_declares_a_source(self):
        """A new detector must not silently fall through to 'unknown' — that
        would make the source-breadth gate quietly wrong."""
        t = _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1})
        missing = [d.__name__ for d in t._signal_detectors
                   if d.__name__.replace('_detect_', '') not in SIGNAL_SOURCES]
        assert missing == []

    def test_squeeze_is_not_flow(self):
        assert SIGNAL_SOURCES['squeeze'] == 'volatility'

    def test_volatility_surge_counts_as_flow(self):
        """It is a volatility detector but its direction is sign(cvd), and the
        gate cares about where the *direction* came from."""
        assert SIGNAL_SOURCES['volatility_surge'] == 'flow'

    def test_unknown_sub_type_falls_back(self):
        assert _gate_card(sub_type='brand_new_detector').source == DEFAULT_SIGNAL_SOURCE

    def test_flow_cluster_is_one_source(self):
        """cvd_momentum + large_trade + cvd_absorption look like three signals
        but carry one piece of information."""
        cards = [_gate_card(sub_type=s) for s in
                 ('cvd_momentum', 'large_trade', 'cvd_absorption')]
        assert len({c.source for c in cards}) == 1


class TestSourceBreadthGate:
    """Breadth by independent source, switched on by a non-zero min_sources.

    There is no shadow/observe-only state: the diagnostic line reports
    `sources=N[...]` per pulse with the same helper, list and direction this gate
    uses, so "would it block?" is derivable from the log rather than needing a
    second verdict channel.  See the config comment.
    """

    def _trigger(self, min_sources=2):
        return _full_trigger({'min_active_non_trend': 3, 'min_active_trend': 1,
                              'min_sources_non_trend': min_sources})

    def _flow_only_signals(self):
        return [_gate_card(sub_type=s) for s in
                ('cvd_momentum', 'large_trade', 'cvd_absorption')]

    def _mixed_signals(self):
        return [_gate_card(sub_type='cvd_momentum'),
                _gate_card(sub_type='large_trade'),
                _gate_card(sub_type='boundary_test')]

    def _metrics(self):
        return _full_metrics(cvd=0.60, price=4400.0)

    def test_disabled_by_default_uses_the_count_gate(self):
        """min_sources=0 must leave today's behaviour untouched."""
        t = self._trigger(min_sources=0)
        res, _ = t._run_pre_ai_gate(self._metrics(), self._flow_only_signals(),
                                    Direction.BULLISH, 'ranging')
        assert res == 'PASS'          # three same-direction flow signals

    def test_enabled_blocks_a_single_source(self):
        t = self._trigger()
        res, reason = t._run_pre_ai_gate(self._metrics(), self._flow_only_signals(),
                                         Direction.BULLISH, 'ranging')
        assert res == 'FAIL'
        assert 'MIN_INDEPENDENT_SOURCES' in reason

    def test_enabled_passes_mixed_sources(self):
        t = self._trigger()
        res, _ = t._run_pre_ai_gate(self._metrics(), self._mixed_signals(),
                                    Direction.BULLISH, 'ranging')
        assert res == 'PASS'

    def test_enabled_replaces_the_count_gate_rather_than_stacking(self):
        """Two signals from two independent sources must pass even though the
        count gate would demand three — otherwise one doubt is counted twice."""
        t = self._trigger()
        two_sources = [_gate_card(sub_type='cvd_momentum'),
                       _gate_card(sub_type='boundary_test')]
        res, _ = t._run_pre_ai_gate(self._metrics(), two_sources,
                                    Direction.BULLISH, 'ranging')
        assert res == 'PASS'

    def test_trending_uses_its_own_source_minimum(self):
        t = _full_trigger({'min_active_non_trend': 1, 'min_active_trend': 1,
                           'min_sources_non_trend': 2, 'min_sources_trend': 0})
        res, _ = t._run_pre_ai_gate(self._metrics(), self._flow_only_signals(),
                                    Direction.BULLISH, 'trending')
        assert res == 'PASS'          # trend min is 0 → count gate (>=1)


# ═══════════════════════════════════════════════════════════════════════════
# Adaptive (scale-free) thresholds
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Self-review regressions
# ═══════════════════════════════════════════════════════════════════════════

class TestSelfReviewRegressions:
    """Each of these pins a defect found by reviewing this change."""

    def test_cvd_divergence_is_not_grouped_with_flow(self):
        """Its direction is contrarian *price*, not sign(cvd).  Grouping it with
        the four sign(cvd) detectors understated the independent-source count and
        made the shadow gate read as blocking more often than it should."""
        assert SIGNAL_SOURCES['cvd_divergence'] != 'flow'
        flow = {s for s, src in SIGNAL_SOURCES.items() if src == 'flow'}
        assert flow == {'cvd_momentum', 'cvd_absorption', 'large_trade',
                        'volatility_surge'}

    def test_each_source_group_has_an_explicit_rationale(self):
        """Sources are defined by where the *direction* comes from; a detector
        whose direction is derived from something else must not share a group."""
        # sign(cvd) group — verified against the detectors' own code
        assert SIGNAL_SOURCES['cvd_momentum'] == 'flow'
        assert SIGNAL_SOURCES['cvd_absorption'] == 'flow'
        assert SIGNAL_SOURCES['large_trade'] == 'flow'
        assert SIGNAL_SOURCES['volatility_surge'] == 'flow'
        # everything else is a distinct provenance
        assert SIGNAL_SOURCES['cvd_divergence'] == 'divergence'
        assert SIGNAL_SOURCES['positioning_extreme'] == 'positioning'
        assert SIGNAL_SOURCES['liquidation_hunt'] == 'liquidity'
        assert SIGNAL_SOURCES['boundary_test'] == 'structure'

    def test_ui_strip_is_re_sorted_by_source(self):
        """Block order from the daemon interleaves sources (cvd_divergence sits
        between two flow detectors), so grouping needs a stable re-sort applied
        by both the render and the update path."""
        from pathlib import Path as _P
        tpl = _P("src/dashboard/templates/live.html").read_text()
        assert 'function _orderedSignals(' in tpl
        assert tpl.count('_orderedSignals(sd)') >= 2, \
            "render and update must use the same ordering"

class TestSourceCountIsDefinedOnce:
    """The gate, the diagnostic line and the pulse file must report the same
    number — an operator reading the log is entitled to read the gate's number.

    An earlier version computed it three ways, and the diagnostic unioned both
    directions: on 18 XAUT pulses it said 2 sources where the gate saw 1.
    """

    def _cards(self):
        from src.sniper.trigger import SignalCard as SC
        now = datetime.now(timezone.utc)
        def mk(sub, direction, strength=0.6):
            return SC(signal_id=sub, sub_type=sub, direction=direction,
                      strength=strength, weight=0.5, timestamp=now,
                      decay_half_life_minutes=10)
        return mk

    def test_direction_is_respected(self):
        from src.sniper.trigger import independent_sources
        mk = self._cards()
        stack = [mk('cvd_momentum', Direction.BEARISH),
                 mk('positioning_extreme', Direction.BULLISH)]
        assert independent_sources(stack, Direction.BEARISH) == ['flow']
        assert independent_sources(stack, Direction.BULLISH) == ['positioning']
        # the old union-of-both-directions answer
        assert len(independent_sources(stack, Direction.BEARISH)) == 1

    def test_weak_signals_do_not_count(self):
        from src.sniper.trigger import independent_sources
        mk = self._cards()
        stack = [mk('cvd_momentum', Direction.BULLISH, strength=0.05),
                 mk('positioning_extreme', Direction.BULLISH, strength=0.6)]
        assert independent_sources(stack, Direction.BULLISH) == ['positioning']

    def test_neutral_direction_never_counts(self):
        from src.sniper.trigger import independent_sources
        mk = self._cards()
        stack = [mk('squeeze', Direction.NEUTRAL, strength=0.9)]
        assert independent_sources(stack, Direction.NEUTRAL) == []
        assert independent_sources(stack, Direction.BULLISH) == []

    def test_accepts_plain_dicts(self):
        from src.sniper.trigger import independent_sources
        stack = [{"direction": "BULLISH", "strength": 0.6, "source": "flow"}]
        assert independent_sources(stack, "BULLISH") == ['flow']
        assert independent_sources(stack, Direction.BULLISH) == ['flow']

    def test_same_source_twice_counts_once(self):
        from src.sniper.trigger import independent_sources
        mk = self._cards()
        stack = [mk('cvd_momentum', Direction.BULLISH),
                 mk('large_trade', Direction.BULLISH),
                 mk('cvd_absorption', Direction.BULLISH)]
        assert independent_sources(stack, Direction.BULLISH) == ['flow']



class TestUiSourceCountAgreesWithTheGate:
    """The panel must not re-derive the source count with different rules.

    The backend computes it once (`independent_sources`, dominant direction
    only).  An earlier UI fallback used `direction !== 'NEUTRAL'`, i.e. it
    unioned both directions and reported 2 sources where the gate saw 1 — the
    same defect the backend had, left alive on the display path.
    """

    def _tpl(self):
        from pathlib import Path
        return Path("src/dashboard/templates/live.html").read_text()

    def test_panel_prefers_the_backend_value(self):
        tpl = self._tpl()
        assert "var names = sd.sources;" in tpl
        assert "if (names && names.length) return names;" in tpl

    def test_fallback_filters_on_the_dominant_direction(self):
        tpl = self._tpl()
        assert "g.direction === sd.direction" in tpl
        # the exact predicate, not the prose in the comment above it
        assert "g.direction !== 'NEUTRAL'" not in tpl, \
            "the union-of-both-directions fallback is back"

    def test_no_permanent_label_beside_the_strip(self):
        """The aggregate lives in the hover tooltip instead.  A permanent label
        was always-on chrome for information the strip already encodes (blocks
        sorted by source, a gap per source change) and that hover can state
        explicitly."""
        tpl = self._tpl()
        assert "signal-strip-sources" not in tpl
        assert "function _sourceBadge(" not in tpl
        assert "function _shouldShowSourceBadge(" not in tpl

    def test_tooltip_states_signal_and_source_counts(self):
        tpl = self._tpl()
        assert "function _sourceSummary(" in tpl
        assert "signals from " in tpl
        # only when it can disambiguate: one signal is already unambiguous
        assert "if (n < 2) return '';" in tpl
        # both the render and the update path must carry it
        assert tpl.count("_sourceSummary(sd)") >= 2

    def test_helper_functions_are_not_duplicated(self):
        """A bad range edit once duplicated the whole helper block; later
        definitions win silently, so only a count catches it."""
        tpl = self._tpl()
        for fn in ("function _esc(", "function _activeSources(", "function _orderedSignals("):
            assert tpl.count(fn) == 1, f"{fn} defined {tpl.count(fn)} times"

    def test_api_forwards_the_source_fields(self):
        from pathlib import Path
        api = Path("src/dashboard/api/sniper_run.py").read_text()
        assert '"sources": entry.get("sources", [])' in api
        assert '"sources_active"' in api
