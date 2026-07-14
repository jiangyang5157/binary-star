import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import List, Tuple

from src.infrastructure.exchange.models import KlineData
from src.utils.logger_utils import setup_logger

logger = setup_logger(__name__)


def _spaced_sample(klines: List[KlineData], count: int) -> List[datetime]:
    """Evenly-spaced fallback when no noteworthy events are found."""
    if not klines or count <= 0:
        return []
    if len(klines) <= count:
        logger.warning(f"requested {count} samples but only {len(klines)} available — returning all")
        indices = range(len(klines))
    else:
        indices = np.linspace(0, len(klines) - 1, count, dtype=int)
    return [datetime.fromtimestamp(klines[i].open_time / 1000, tz=timezone.utc) for i in indices]


class SniperSampler:
    """
    Intelligence-Led Sampler.

    Scans the historical range for 'Noteworthy' events (Squeezes, CVD extremes,
    Volatility Ignition) using the Sniper Wake-Up Matrix, then returns a
    stratified proportional sample across event types.

    Falls back to evenly-spaced sampling if the range contains no asymmetry.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        # Lazy imports to avoid circular dependencies
        from src.sniper.scout import SniperScout
        from src.sniper.trigger import SniperTrigger

        self.scout = SniperScout(symbol)
        self.trigger = SniperTrigger(strategy_cfg=self.scout.strategy_cfg, global_cfg=self.scout.global_cfg)

    def sample(self, klines: List[KlineData], count: int) -> List[datetime]:
        """
        Scans the historical timeline for asymmetry and picks the most
        noteworthy points via stratified proportional sampling.
        """
        if not klines or count <= 0:
            return []

        logger.info(f"scanning {len(klines)} candidate points for noteworthy events")

        noteworthy_points: List[Tuple[datetime, str]] = []
        prev_metrics = None

        for kline in klines:
            dt = datetime.fromtimestamp(kline.open_time / 1000, tz=timezone.utc)

            try:
                # 1. Scout the historical moment
                res = self.scout.scout(at_time=dt)
                if not res.metrics:
                    continue

                # 2. Evaluate for 'Interest'
                result = self.trigger.evaluate(res.metrics, prev_metrics)
                is_noteworthy = result.triggered
                event_type = result.gate_result

                if is_noteworthy:
                    logger.info(f"noteworthy event found | dt={dt} | type={event_type}")
                    noteworthy_points.append((dt, event_type))
                    # Reset the trigger cooldown state in memory for sampling
                    self.trigger.last_trigger_time = None

                prev_metrics = res.metrics

            except Exception as e:
                logger.error(f"error scanning event | dt={dt} | error={e}")
                continue

        if not noteworthy_points:
            logger.warning("no noteworthy events — falling back to evenly-spaced sampling")
            return _spaced_sample(klines, count)

        # Proportional Sampling across event types
        event_df = pd.DataFrame(noteworthy_points, columns=['timestamp', 'type'])

        if len(event_df) <= count:
            return event_df['timestamp'].tolist()

        # Stratified sample by event type (at least 1 per group, capped at count)
        sampled_rows = event_df.groupby('type', group_keys=False).apply(
            lambda x: x.sample(n=min(len(x), max(1, int(len(x) / len(event_df) * count))))
        )
        if len(sampled_rows) > count:
            sampled_rows = sampled_rows.sample(count)

        if len(sampled_rows) < count:
            remaining = event_df[~event_df.index.isin(sampled_rows.index)]
            fill_count = min(len(remaining), count - len(sampled_rows))
            if fill_count > 0:
                sampled_rows = pd.concat([sampled_rows, remaining.sample(fill_count)])

        return sorted(sampled_rows['timestamp'].tolist())
