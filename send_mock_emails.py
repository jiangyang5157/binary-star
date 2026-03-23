import os
import yaml
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from src.utils.notifier import EmailNotifier

def send_mock_emails():
    # Load config
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    notifier = EmailNotifier(config)
    if not notifier.enabled:
        print("Notifier not enabled. Check .env for RECIPIENT_EMAIL and RECIPIENT_APP_PASSWORD.")
        return

    symbol = "BTCUSDT"
    
    # Existing images for testing
    img_dir = "data/images"
    chart_paths = [
        os.path.join(img_dir, "BTCUSDT_1h_20260323_071539Z_chart.png"),
        os.path.join(img_dir, "BTCUSDT_15m_20260323_071539Z_chart.png")
    ]
    # Filter only those that exist
    chart_paths = [p for p in chart_paths if os.path.exists(p)]

    # 1. Mock Prediction
    prediction = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "opinion": "BULLISH",
        "confidence": 85,
        "action": "LONG",
        "current_price": 65432.10,
        "take_profit": 68000.00,
        "stop_loss": 64000.00,
        "reasoning_zh": "由于RSI在40附近反弹且MACD出现金叉，市场显示出强劲的看涨信号。HVN区支撑有力。",
        "position_context": {"position_type": "NONE", "entry_price": None},
        "config_context": {"prediction_horizon_days": 3}
    }
    
    print(f"Sending mock prediction email for {symbol} with {len(chart_paths)} charts...")
    notifier.send_prediction_alert(symbol, prediction, chart_paths=chart_paths)

    # 2. Mock Review
    # Manually backdate the prediction timestamp for the review to show elapsed time
    prediction_time_for_review = datetime.now(ZoneInfo("Pacific/Auckland")) - timedelta(hours=2, minutes=30)
    
    # Create a copy of the prediction and update its timestamp for the review context
    mock_prediction_for_review = prediction.copy()
    mock_prediction_for_review["timestamp"] = prediction_time_for_review.isoformat()

    review_record = {
        "symbol": "BTCUSDT",
        "evaluation_score": 95,
        "tp_sl_result": "TP_HIT",
        "mae_stress_level": "4.5%",  # Test green color logic (<=5%)
        "prediction_post_mortem_zh": "由于BTC在支撑位表现强劲，且MACD底背离确认，价格如预期触及TP目标位。持仓期间最大回撤极小，展现了极高的入场精度。",
        "prediction": mock_prediction_for_review, # Use the backdated prediction
        "review_timestamp": datetime.now(ZoneInfo("Pacific/Auckland")).isoformat(),
        "actual_market_outcome": {
            "max_drawdown_pct": -0.44,
            "max_drawup_pct": 5.84
        }
    }
    
    print(f"Sending mock review email for {symbol}...")
    notifier.send_review_alert(symbol, review_record)

if __name__ == "__main__":
    send_mock_emails()
