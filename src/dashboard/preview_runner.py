"""Standalone subprocess for computing backtest preview samples.

Spawned by the dashboard API so the preview is cancellable and survives
page refreshes.  Writes results to .backtest_status.json.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()


def main():
    """Entry point: read args from stdin JSON, compute samples, write status."""
    args = json.loads(sys.stdin.read())

    data_root = args["data_root"]
    mode = args["mode"]
    symbol = args["symbol"]
    timestamp_str = args.get("timestamp")
    start_str = args.get("start")
    end_str = args.get("end")
    samples = args.get("samples")

    from src.dashboard.api.backtest import _compute_samples, _read_status, _write_status
    from logging import getLogger
    log = getLogger(__name__)

    try:
        ts_list = _compute_samples(
            mode=mode,
            symbol=symbol,
            timestamp_str=timestamp_str,
            start_str=start_str,
            end_str=end_str,
            samples=samples,
        )

        status = _read_status(data_root) or {}
        status.update({
            "running": False,
            "mode": mode,
            "symbol": symbol,
            "samples": [
                {"timestamp": ts, "status": "pending"}
                for ts in ts_list
            ],
        })
        _write_status(data_root, status)
        log.info("Preview complete: %d samples for %s", len(ts_list), symbol)

    except Exception as e:
        log.exception("Preview failed for %s", symbol)
        status = _read_status(data_root) or {}
        status.update({
            "running": False,
            "error": str(e),
        })
        _write_status(data_root, status)
        sys.exit(1)


if __name__ == "__main__":
    main()
