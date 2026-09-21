"""Tests for Sniper Trigger — SignalCard, SignalMemory, ConfluenceEngine."""
import math
from datetime import datetime, timezone, timedelta
import pytest
from src.sniper.trigger import (
    SignalCard, SignalMemory, ConfluenceEngine, Direction, SniperTrigger,
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
    # BTC overrides trigger_threshold to 0.36 and cvd_divergence_tick_delta to 0.08
    thresholds = trigger_btc.sniper_cfg.get("signal_stack", {}).get("thresholds", {})
    assert thresholds.get("cvd_divergence_tick_delta") == 0.08
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
        'analysis_window': {'macro_context': {'time_interval': '1h'}},
    }
    sniper = {
        'signal_stack': {
            'trigger_threshold': 0.34, 'emergency_threshold': 0.80,
            'regime_modifiers': {'trending': 0.85, 'ranging': 1.0, 'squeeze': 0.75, 'chaos': 1.5},
            'weights': _WEIGHTS, 'decay': _DECAY,
            'cooldown': {'regime_base_minutes': {'trending': 20, 'ranging': 40,
                                                 'squeeze': 20, 'chaos': 60},
                         'neutral_multiplier': 0.8, 'failure_cooldown_minutes': 3},
            'thresholds': {'cvd_divergence_tick_delta': 0.12, 'cvd_extreme_threshold': 0.24,
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
