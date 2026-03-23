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
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "opinion": "BULLISH",
        "confidence": 85,
        "action": "LONG",
        "current_price": 65432.10,
        "take_profit": 68000.00,
        "stop_loss": 64000.00,
        "reasoning": "The RSI is bouncing off 40 and MACD is showing a bullish crossover. HVN support is solid.",
        "reasoning_zh": "由于RSI在40附近反弹且MACD出现金叉，市场显示出强劲的看涨信号。HVN区支撑有力。",
        "position_context": {"position_type": "NONE", "entry_price": 0.0},
        "config_context": {
            "symbol": "BTCUSDT",
            "prediction_horizon_days": 3,
            "model": "gpt-4-mock"
        },
        "extra_metadata": {
            "market_regime": "TRENDING_UP",
            "val": 63500.0,
            "vah": 67200.0,
            "poc": 65800.0
        }
    }
    
    print(f"Sending mock prediction email for {symbol} with {len(chart_paths)} charts...")
    notifier.send_prediction_alert(symbol, prediction, chart_paths=chart_paths)

    # 2. Mock Review
    # Manually backdate the prediction timestamp for the review to show elapsed time
    prediction_time_for_review = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)
    
    # Create a copy of the prediction and update its timestamp for the review context
    mock_prediction_for_review = prediction.copy()
    mock_prediction_for_review["timestamp"] = prediction_time_for_review.isoformat().replace("+00:00", "Z")

    review_record = {
        "prediction": {
            "source": f"{symbol}_prediction_mock.json",
            "content": mock_prediction_for_review
        },
        "review_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actual_market_outcome": {
            "start_price": 65432.10,
            "max_price_reached": 68200.00,
            "min_price_reached": 65150.0,
            "final_close_price": 68150.0,
            "max_drawup_pct": 5.84,
            "max_drawdown_pct": -0.44
        },
        "analysis": {
            "evaluation_score": 95,
            "tp_sl_result": "TP_HIT",
            "adversarial_audit": {
                "mae_stress_level": "4.5%",
                "stress_comment": "Excellent entry. Minimal pressure."
            },
            "prediction_post_mortem": "Price hit the TP target exactly as predicted. The support at 65k held perfectly.",
            "prediction_post_mortem_zh": "由于BTC在支撑位表现强劲，且MACD底背离确认，价格如预期触及TP目标位。持仓期间最大回撤极小，展现了极高的入场精度。"
        }
    }
    
    print(f"Sending mock review email for {symbol}...")
    notifier.send_review_alert(symbol, review_record)

if __name__ == "__main__":
    send_mock_emails()
