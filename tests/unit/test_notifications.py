"""Tests for the notification system (email templates, dispatcher, session notifier)."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.infrastructure.notifications.base_notifier import (
    NotificationConfig, BaseEmailTemplate, EmailDispatcher,
)
from src.infrastructure.notifications.email_notifier import (
    AlertEmailTemplate, SessionNotifier,
)


class TestNotificationConfig:
    def test_from_env_disabled_when_missing(self):
        """Returns disabled config when env vars are absent."""
        with patch("src.infrastructure.notifications.base_notifier.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True):
            cfg = NotificationConfig.from_env()
        assert cfg.enabled is False
        assert cfg.sender_email == ""


class TestEmailDispatcher:
    def test_dispatch_disabled(self):
        """Returns False immediately when config is disabled."""
        cfg = NotificationConfig("smtp", 587, "", "", enabled=False)
        d = EmailDispatcher(cfg)
        assert d.dispatch("sub", "<html/>") is False


class TestAlertEmailTemplate:
    def test_render_contains_alert_name(self):
        html = AlertEmailTemplate.render("TEST_ALERT", "BTCUSDT", "something broke")
        assert "TEST_ALERT" in html
        assert "BTCUSDT" in html
        assert "something broke" in html

    def test_render_includes_metadata(self):
        meta = {"circuit": "breaker", "count": 3}
        html = AlertEmailTemplate.render("ALERT", "X", "err", metadata=meta)
        assert "circuit" in html
        assert "breaker" in html

    def test_render_no_metadata(self):
        html = AlertEmailTemplate.render("ALERT", "X", "err")
        assert "METADATA" not in html or "Audit Context" not in html  # metadata section absent


class TestSessionNotifier:
    def test_enabled_property(self):
        sn = SessionNotifier("data/test")
        assert isinstance(sn.enabled, bool)  # should not raise

    def test_get_timestamp_suffix_fallback(self):
        sn = SessionNotifier("data/test")
        ts = sn._get_timestamp_suffix({})
        assert len(ts) > 0
        # Should be a timestamp string like "20260701_120000"

    def test_get_timestamp_suffix_from_obs(self):
        sn = SessionNotifier("data/test")
        ts = sn._get_timestamp_suffix({"observed_at": "2026-07-01T12:00:00Z"})
        assert "20260701" in ts

    @patch.object(EmailDispatcher, "dispatch", return_value=True)
    def test_notify_session_skipped_low_confidence(self, mock_dispatch):
        sn = SessionNotifier("data/test")
        sn.config = NotificationConfig("smtp", 587, "a@b", "pw", enabled=True)
        with patch.object(sn, "confidence_threshold", 50):
            result = sn.notify_session("BTCUSDT", {
                "final_decision": {"confidence_score": 30, "opinion": "BULLISH"},
            })
            assert result is False  # skipped below threshold
            mock_dispatch.assert_not_called()

    @patch.object(EmailDispatcher, "dispatch", return_value=True)
    def test_notify_session_dispatches(self, mock_dispatch):
        sn = SessionNotifier("data/test")
        sn.config = NotificationConfig("smtp", 587, "a@b", "pw", enabled=True)
        with patch.object(sn, "confidence_threshold", 50):
            result = sn.notify_session("BTCUSDT", {
                "final_decision": {"confidence_score": 80, "opinion": "BULLISH"},
            })
            assert result is True
            mock_dispatch.assert_called_once()

    def test_save_html_preview_creates_file(self, tmp_path):
        sn = SessionNotifier("data/test")
        with patch.object(sn, "data_root", str(tmp_path)):
            path = sn.save_html_preview("test_preview.html", "<html/>")
            assert path is not None
            assert tmp_path.joinpath("html", "test_preview.html").exists()

    def test_notify_alert_dispatched(self):
        sn = SessionNotifier("data/test")
        sn.config = NotificationConfig("smtp", 587, "a@b", "pw", enabled=True)
        with patch.object(EmailDispatcher, "dispatch", return_value=True) as mock_dispatch:
            result = sn.notify_alert("CRASH", "BTCUSDT", "market down")
            assert result is True
            mock_dispatch.assert_called_once()
