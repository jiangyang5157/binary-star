"""Regression tests: every Binance REST client must carry a real HTTP timeout.

Why this file exists
--------------------
The daemon runs unattended for days, so one unbounded ``requests`` call can
freeze the pulse loop indefinitely.  A previous fix "bounded" the Spot client by
setting ``self.client.REQUEST_TIMEOUT`` — an attribute that does not exist on
``binance.spot.Spot``, so the assignment silently did nothing and production kept
logging ``Read timed out. (read timeout=None)``.  Asserting the attribute is
therefore worthless; these tests assert the timeout actually reaches the HTTP
dispatch, which is the only contract that matters.
"""
import pytest

from src.infrastructure.binance.net_config import (
    DEFAULT_API_TIMEOUT_SECONDS,
    get_api_timeout_seconds,
    load_binance_net_config,
)


class _FakeResponse:
    """Minimal stand-in for the ``requests`` response ``send_request`` expects."""
    status_code = 200
    text = "{}"
    headers = {}

    def json(self):
        return {}


def _capture_request(binance_client):
    """Patch the lowest dispatch point so the next request records its kwargs."""
    seen = {}

    def fake_dispatch(http_method):
        def call(**kwargs):
            seen.update(kwargs)
            seen["http_method"] = http_method
            return _FakeResponse()
        return call

    binance_client._dispatch_request = fake_dispatch
    return seen


# ── the timeout actually reaches the wire ────────────────────────────────────

def test_futures_client_sends_configured_timeout():
    from src.infrastructure.binance.client import BinanceFuturesClient

    c = BinanceFuturesClient(api_key="k", api_secret="s")
    assert c.timeout == get_api_timeout_seconds()

    seen = _capture_request(c.client)
    c.client.send_request("GET", "/fapi/v1/time")

    assert seen["timeout"] == c.timeout


def test_futures_public_client_sends_configured_timeout():
    """The unauthenticated client is the one the daemon's read path uses."""
    from src.infrastructure.binance.client import BinanceFuturesClient

    c = BinanceFuturesClient(api_key=None, api_secret=None)
    seen = _capture_request(c.client)
    c.client.send_request("GET", "/fapi/v1/time")

    assert seen["timeout"] == get_api_timeout_seconds()


def test_margin_client_sends_configured_timeout():
    """Spot/margin is where the dead REQUEST_TIMEOUT knob lived."""
    from src.infrastructure.binance.margin_client import BinanceMarginClient

    c = BinanceMarginClient(api_key="k", api_secret="s")
    seen = _capture_request(c.client)
    c.client.send_request("GET", "/sapi/v1/margin/account")

    assert seen["timeout"] == c.timeout


@pytest.mark.parametrize("factory", [
    lambda: __import__("src.infrastructure.binance.client", fromlist=["x"])
            .BinanceFuturesClient(api_key="k", api_secret="s").client,
    lambda: __import__("src.infrastructure.binance.margin_client", fromlist=["x"])
            .BinanceMarginClient(api_key="k", api_secret="s").client,
])
def test_timeout_is_never_none(factory):
    """``None`` means "wait forever" — the exact production freeze."""
    client = factory()
    seen = _capture_request(client)
    client.send_request("GET", "/time")

    assert seen["timeout"] is not None
    assert seen["timeout"] > 0


# ── config resolution ────────────────────────────────────────────────────────

def test_configured_timeout_is_read_from_global_config():
    assert get_api_timeout_seconds() == load_binance_net_config()["api_timeout_seconds"]


@pytest.mark.parametrize("bad", ["garbage", None, 0, -5])
def test_invalid_timeout_falls_back_to_default(monkeypatch, bad):
    import src.infrastructure.binance.net_config as net

    monkeypatch.setattr(net, "load_binance_net_config", lambda: {"api_timeout_seconds": bad})
    assert net.get_api_timeout_seconds() == DEFAULT_API_TIMEOUT_SECONDS


def test_missing_timeout_key_falls_back_to_default(monkeypatch):
    import src.infrastructure.binance.net_config as net

    monkeypatch.setattr(net, "load_binance_net_config", lambda: {})
    assert net.get_api_timeout_seconds() == DEFAULT_API_TIMEOUT_SECONDS
