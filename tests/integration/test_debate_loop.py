"""Test DebateLoop with mocked agents."""
from unittest.mock import MagicMock
from src.agent.debate_loop import DebateLoop


def _make_mock_config(model_temperature=0.7):
    """Build a mock config with nested regime/risk/temporal attributes."""
    cfg = MagicMock()
    cfg.model_temperature = model_temperature
    cfg.regime = MagicMock()
    cfg.regime.squeeze_audit_threshold = 0.85
    cfg.regime.min_volume_participation_ratio = 1.0
    cfg.regime.poc_gravity_atr_distance = 3.0
    cfg.regime.cvd_intensity_threshold = 0.1
    cfg.regime.cvd_intensity_extreme = 0.35
    cfg.regime.trend_intensity_strong = 0.35
    cfg.regime.volatility_baseline_ratio = 1.3
    cfg.regime.volatility_extreme_ratio = 2.0
    cfg.risk = MagicMock()
    cfg.risk.poc_gravity_atr_distance = 3.0
    cfg.risk.structural_buffer_atr = 0.05
    cfg.temporal = MagicMock()
    cfg.temporal.min_trade_velocity = 0.4
    return cfg


def test_debate_loop_exits_on_pass():
    """DebateLoop exits early when Critic returns PASS."""
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BULLISH",
        "confidence_score": 85,
        "tactical_parameters": {
            "entry": 100, "stop_loss": 98, "take_profit": 106,
        },
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.return_value = {
        "veto_level": "PASS", "invalidations": [],
    }

    mock_math = MagicMock()
    mock_math.verify.return_value = {
        "status": "VERIFIED", "compliance_verdict": {},
    }

    loop = DebateLoop(
        session_agent=mock_session,
        critic_agent=mock_critic,
        math_checker=mock_math,
        max_rounds=3,
        tools=[],
        shared_instruction="Test instruction",
        session_config=_make_mock_config(0.7),
        critic_config=_make_mock_config(0.2),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert result["early_exit"] is True
    assert result["final_decision"]["opinion"] == "BULLISH"


def test_debate_loop_exits_on_weak():
    """DebateLoop exits early when Critic returns WEAK."""
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BEARISH",
        "confidence_score": 50,
        "tactical_parameters": {
            "entry": 100, "stop_loss": 102, "take_profit": 94,
        },
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.return_value = {
        "veto_level": "WEAK", "invalidations": ["minor_RR_issue"],
    }

    mock_math = MagicMock()
    mock_math.verify.return_value = {
        "status": "VERIFIED", "compliance_verdict": {},
    }

    loop = DebateLoop(
        session_agent=mock_session,
        critic_agent=mock_critic,
        math_checker=mock_math,
        max_rounds=3,
        tools=[],
        shared_instruction="Test instruction",
        session_config=_make_mock_config(0.7),
        critic_config=_make_mock_config(0.2),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert result["early_exit"] is True
    assert result["final_decision"]["opinion"] == "BEARISH"


def test_debate_loop_runs_full_rounds():
    """DebateLoop runs max_rounds when Critic never passes."""
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BULLISH",
        "confidence_score": 85,
        "tactical_parameters": {
            "entry": 100, "stop_loss": 98, "take_profit": 106,
        },
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.return_value = {
        "veto_level": "TERMINAL", "invalidations": ["unshielded_SL"],
    }

    mock_math = MagicMock()
    mock_math.verify.return_value = {
        "status": "VERIFIED", "compliance_verdict": {},
    }

    loop = DebateLoop(
        session_agent=mock_session,
        critic_agent=mock_critic,
        math_checker=mock_math,
        max_rounds=3,
        tools=[],
        shared_instruction="Test instruction",
        session_config=_make_mock_config(0.7),
        critic_config=_make_mock_config(0.2),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert result["early_exit"] is False
    assert len(result["debate_history"]) == 3
    assert mock_session.execute_session_cycle.call_count == 3


def test_debate_loop_compresses_history():
    """Debate history entries are compressed for token efficiency."""
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BULLISH",
        "confidence_score": 85,
        "tactical_parameters": {
            "entry": 100, "stop_loss": 98, "take_profit": 106,
        },
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.side_effect = [
        {"veto_level": "TERMINAL", "invalidations": ["risk"], "critic_summary": "bad"},
        {"veto_level": "CONSTRUCTIVE", "invalidations": ["mild"], "critic_summary": "ok"},
        {"veto_level": "PASS", "invalidations": [], "critic_summary": "good"},
    ]

    mock_math = MagicMock()
    mock_math.verify.return_value = {
        "status": "VERIFIED", "compliance_verdict": {},
    }

    loop = DebateLoop(
        session_agent=mock_session,
        critic_agent=mock_critic,
        math_checker=mock_math,
        max_rounds=3,
        tools=[],
        shared_instruction="Test instruction",
        session_config=_make_mock_config(0.7),
        critic_config=_make_mock_config(0.2),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert result["early_exit"] is True
    assert len(result["debate_history"]) == 3
    # Verify compressed history passed to later session calls
    # Round 2 call should receive compressed history from round 1
    call2 = mock_session.execute_session_cycle.call_args_list[1]
    deb_history_r2 = call2.kwargs["debate_history"]
    assert len(deb_history_r2) == 1
    # Older round should be compressed (no reasoning_chain)
    assert "reasoning_chain" not in deb_history_r2[0]["plan"]


def test_debate_loop_math_check_called_every_round():
    """MathFactChecker.verify is called for every round."""
    mock_session = MagicMock()
    mock_session.execute_session_cycle.return_value = {
        "opinion": "BULLISH",
        "confidence_score": 85,
        "tactical_parameters": {
            "entry": 100, "stop_loss": 98, "take_profit": 106,
        },
    }
    mock_critic = MagicMock()
    mock_critic.evaluate.return_value = {
        "veto_level": "CONSTRUCTIVE", "invalidations": [],
    }

    mock_math = MagicMock()
    mock_math.verify.return_value = {
        "status": "VERIFIED", "compliance_verdict": {},
    }

    loop = DebateLoop(
        session_agent=mock_session,
        critic_agent=mock_critic,
        math_checker=mock_math,
        max_rounds=2,
        tools=[],
        shared_instruction="Test instruction",
        session_config=_make_mock_config(0.7),
        critic_config=_make_mock_config(0.2),
    )
    result = loop.run({"quantitative_metrics": {}}, "BTCUSDT")

    assert len(result["debate_history"]) == 2
    assert mock_math.verify.call_count == 2
