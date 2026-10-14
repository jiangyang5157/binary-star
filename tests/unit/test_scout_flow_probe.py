"""The flow probe is instrumentation only: it must never change metrics, and it
must never break a pulse."""
import logging
from types import SimpleNamespace

import src.sniper.scout as scout_mod


def _scout(lookback=4):
    s = object.__new__(scout_mod.SniperScout)
    s.symbol = "XAUTUSDT"
    s.obs_config = SimpleNamespace(cvd_micro_lookback_candles=lookback)
    return s


def _kline(delta, volume):
    return SimpleNamespace(taker_buy_base=(volume + delta) / 2, volume=volume)


def _probe_text(caplog, klines, lookback=4):
    with caplog.at_level(logging.INFO, logger="src.sniper.scout"):
        _scout(lookback)._log_flow_probe(SimpleNamespace(micro_klines=klines))
    # getMessage() already interpolates args
    return "\n".join(r.getMessage() for r in caplog.records
                      if "FLOW PROBE" in r.getMessage())


def test_emits_newest_first(caplog):
    text = _probe_text(caplog, [_kline(+1.0, 10.0), _kline(-2.0, 8.0),
                                _kline(+0.5, 6.0), _kline(+3.0, 9.0), _kline(+0.2, 1.0)])
    assert "[+0.2000,1.0000]" in text          # forming candle first
    assert text.index("+0.2000") < text.index("+3.0000")


def test_limits_to_the_configured_lookback(caplog):
    text = _probe_text(caplog, [_kline(float(i), 1.0) for i in range(10)], lookback=4)
    payload = text.split("flow=", 1)[1]          # ignore the "[SYMBOL] " prefix
    assert payload.count("[") == 4


def test_empty_klines_emit_nothing(caplog):
    assert _probe_text(caplog, []) == ""


def test_missing_taker_data_emits_nothing(caplog):
    assert _probe_text(caplog, [SimpleNamespace(taker_buy_base=None, volume=1.0)]) == ""


def test_never_raises_on_garbage(caplog):
    """Instrumentation must not be able to break a pulse."""
    with caplog.at_level(logging.DEBUG):
        _scout()._log_flow_probe(SimpleNamespace(micro_klines=None))
        _scout()._log_flow_probe(SimpleNamespace(micro_klines=[object()]))
        _scout()._log_flow_probe(SimpleNamespace())   # no attribute at all
