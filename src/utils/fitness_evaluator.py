import logging
from dataclasses import dataclass
from typing import Dict, Any

# Initialize standard logger for forensic fitness tracking
logger = logging.getLogger("FitnessEvaluator")


@dataclass(frozen=True)
class FitnessConfig:
    """
    Type-safe configuration for Darwinian Fitness Evaluation.
    Representative Score Ladder (Default Config):
        TP_HIT (clean, fast, PINPOINT MAE):        115
        TP_HIT (clean, fast, MFE >= 90%):          110
        TP_HIT (clean, standard):                  100
        TP_HIT (clean, slow >48h, proj < 24h):      85
        NEUTRAL (justified surrender):               85
        NEUTRAL (baseline):                          70
        TP_HIT (LOGIC_FAILURE):                      60
        NEITHER (baseline, unfilled):                40
        NEITHER (catastrophic miss):                 20
        SL_HIT (clean):                               5
        SL_HIT (LOGIC_FAILURE):                     -35
    """
    # Base Outcome Scores (synced with global_config.yaml → sandbox.base_scores)
    tp_hit: float = 100.0
    neutral: float = 70.0
    neither: float = 40.0
    sl_hit: float = 5.0
    na: float = 0.0

    # Forensic Modifiers
    logic_failure_penalty: float = -40.0
    luck_penalty: float = -20.0
    slow_lock_penalty: float = -15.0
    smart_surrender_bonus: float = 15.0
    catastrophic_miss_penalty: float = -20.0

    # MFE Execution Quality Bonuses
    mfe_efficiency_bonus_high: float = 10.0
    mfe_efficiency_bonus_medium: float = 5.0
    pinpoint_execution_bonus: float = 5.0

    # Proportional Slow Lock
    slow_lock_ratio: float = 2.0

    # Consecutive Failure Sequence Penalties
    consecutive_failure_base: float = 5.0
    consecutive_failure_escalation: float = 5.0
    recovery_skepticism_penalty: float = 5.0

    # Tie-breaker Thresholds
    mae_significance_threshold: float = 15.0
    mae_improvement_threshold: float = 5.0
    time_improvement_threshold: float = 4.0

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "FitnessConfig":
        """Factory to assemble config from the sandbox block."""
        sandbox = config_dict.get('sandbox', {})
        thresholds = sandbox.get('thresholds', {})
        base = sandbox.get('base_scores', {})
        mods = sandbox.get('modifiers', {})

        return cls(
            tp_hit=float(base.get('tp_hit', 100.0)),
            neutral=float(base.get('neutral', 60.0)),
            neither=float(base.get('neither', 40.0)),
            sl_hit=float(base.get('sl_hit', 15.0)),
            na=float(base.get('na', 0.0)),
            logic_failure_penalty=float(mods.get('logic_failure_penalty', -40.0)),
            luck_penalty=float(mods.get('luck_penalty', -20.0)),
            slow_lock_penalty=float(mods.get('slow_lock_penalty', -15.0)),
            smart_surrender_bonus=float(mods.get('smart_surrender_bonus', 15.0)),
            catastrophic_miss_penalty=float(mods.get('catastrophic_miss_penalty', -20.0)),
            mfe_efficiency_bonus_high=float(mods.get('mfe_efficiency_bonus_high', 10.0)),
            mfe_efficiency_bonus_medium=float(mods.get('mfe_efficiency_bonus_medium', 5.0)),
            pinpoint_execution_bonus=float(mods.get('pinpoint_execution_bonus', 5.0)),
            slow_lock_ratio=float(mods.get('slow_lock_ratio', 2.0)),
            consecutive_failure_base=float(mods.get('consecutive_failure_base', 5.0)),
            consecutive_failure_escalation=float(mods.get('consecutive_failure_escalation', 5.0)),
            recovery_skepticism_penalty=float(mods.get('recovery_skepticism_penalty', 5.0)),
            mae_significance_threshold=float(thresholds.get('mae_significance_threshold', 15.0)),
            mae_improvement_threshold=float(thresholds.get('mae_improvement_threshold', 5.0)),
            time_improvement_threshold=float(thresholds.get('time_improvement_threshold', 4.0))
        )


class FitnessEvaluator:
    """
    Darwinian Fitness Evaluator
    
    A shared, stateless judge that scores market outcomes and compares 
    old vs. new strategy results for the Evolution pipeline.
    """

    def __init__(self, config_dict: Dict[str, Any]):
        """
        Args:
            config_dict: The combined system configuration (global + strategy).
        """
        self.config_dict = config_dict
        self.cfg = FitnessConfig.from_dict(config_dict)

    def get_fitness_score(self, outcome: Dict[str, Any],
                           consecutive_failures: int = 0) -> float:
        """
        Calculates a composite forensic fitness score for a single market outcome.
        Standardizes calculations by sourcing weights from the FitnessConfig.

        Args:
            outcome: The market outcome dict (tp_sl_result, is_filled, metrics, verdict).
            consecutive_failures: Number of consecutive SL_HIT/NEITHER outcomes
                                  preceding this one (for sequence-dependent penalties).
        """
        res = str(outcome.get('tp_sl_result', 'N/A')).upper()
        is_filled = outcome.get('is_filled', False)
        metrics = outcome.get('trade_execution_metrics', {})
        verdict = outcome.get('forensic_verdict', {})

        # --- 1. Base PnL Score ---
        base_map = {
            "TP_HIT": self.cfg.tp_hit,
            "NEUTRAL": self.cfg.neutral,
            "NEITHER": self.cfg.neither,
            "SL_HIT": self.cfg.sl_hit,
            "N/A": self.cfg.na
        }
        score = base_map.get(res, 0.0)

        # --- 2. Execution Quality Assessment (ALL filled trades) ---
        if is_filled:
            mae_tier = str(metrics.get('mae_stress_tier', '')).upper()
            mae_pct = float(metrics.get('mae_stress_level_pct', 0.0))
            hours = float(metrics.get('actual_holding_hours', 0.0))
            mfe_eff = float(metrics.get('mfe_efficiency_pct', 0.0))
            proj_hours = float(metrics.get('projected_holding_hours', 0.0))

            # -- Penalties (unchanged) --
            # LOGIC_FAILURE or MAE >= 100%: Structural defense collapsed
            if mae_tier == "LOGIC_FAILURE" or mae_pct >= 100.0:
                score += self.cfg.logic_failure_penalty
            elif mae_tier == "LUCK":
                score += self.cfg.luck_penalty

            # -- MFE Efficiency Bonuses --
            # Positive reinforcement for clean, efficient execution
            if mfe_eff >= 90.0:
                score += self.cfg.mfe_efficiency_bonus_high
            elif mfe_eff >= 70.0:
                score += self.cfg.mfe_efficiency_bonus_medium

            # PINPOINT execution bonus (minimal adverse excursion)
            if mae_tier == "PINPOINT":
                score += self.cfg.pinpoint_execution_bonus

            # -- Proportional Slow Lock Penalty --
            # Triggered only when actual holding exceeds projected * ratio,
            # avoiding false positives in slow-moving regimes
            if res in ("TP_HIT", "NEITHER") and proj_hours > 0:
                if hours > proj_hours * self.cfg.slow_lock_ratio:
                    score += self.cfg.slow_lock_penalty

        # --- 3. Forensic Verdict Modifiers ---
        # Smart Surrender: Disciplined inaction in a dead market
        if verdict.get('is_justified_surrender') is True:
            score += self.cfg.smart_surrender_bonus

        # Catastrophic Miss: Directional opinion correct, but order never filled
        if verdict.get('is_catastrophic_miss') is True:
            score += self.cfg.catastrophic_miss_penalty

        # --- 4. Consecutive Failure Sequence Penalty ---
        # Penalises patterns of repeated SL_HIT/NEITHER outcomes.
        # A TP_HIT that breaks a long losing streak is also sceptically discounted
        # to avoid rewarding "gambler's recovery."
        if consecutive_failures >= 2:
            if res in ("SL_HIT", "NEITHER"):
                # Escalating penalty: each additional failure adds more
                penalty = (self.cfg.consecutive_failure_base +
                           (consecutive_failures - 2) * self.cfg.consecutive_failure_escalation)
                score -= penalty
                logger.info("[SEQUENCE] %d consecutive failures → %.1f penalty",
                            consecutive_failures, penalty)
            elif res == "TP_HIT" and consecutive_failures >= 3:
                # Recovery scepticism: a win after 3+ losses may be luck
                score -= self.cfg.recovery_skepticism_penalty
                logger.info("[SEQUENCE] TP_HIT after %d consecutive failures → %.1f scepticism",
                            consecutive_failures, self.cfg.recovery_skepticism_penalty)

        return score

    def is_superior(self, old_outcome: Dict[str, Any], new_outcome: Dict[str, Any],
                     consecutive_failures: int = 0,
                     old_consecutive_failures: int = 0,
                     old_score: float | None = None,
                     new_score: float | None = None) -> bool:
        """
        Darwinian Comparison: Evaluates PnL, forensic intelligence,
        and execution efficiency.

        Args:
            old_outcome: The original strategy's market outcome.
            new_outcome: The proposed strategy's market outcome.
            consecutive_failures: Number of consecutive SL_HIT/NEITHER outcomes
                                  in the proposed strategy's sequence preceding
                                  this one.
            old_consecutive_failures: Number of consecutive failures in the
                                      original strategy's sequence preceding
                                      this one. Ensures symmetric penalty.
            old_score: Pre-computed old outcome score (optional). When provided
                       skips internal computation to avoid redundant calls.
            new_score: Pre-computed new outcome score (optional).

        Returns True if the new outcome is strictly better than the old one.
        """
        if old_score is None:
            old_score = self.get_fitness_score(
                old_outcome, consecutive_failures=old_consecutive_failures
            )
        if new_score is None:
            new_score = self.get_fitness_score(
                new_outcome, consecutive_failures=consecutive_failures
            )

        old_res = str(old_outcome.get('tp_sl_result', 'N/A')).upper()
        new_res = str(new_outcome.get('tp_sl_result', 'N/A')).upper()

        # Dimension 1: Absolute Fitness Resolution
        if new_score > old_score:
            logger.info(f"[IMPROVEMENT] score {old_score} → {new_score} | result {old_res} → {new_res}")
            return True
        if new_score < old_score:
            logger.info(f"[NO_IMPROVEMENT] score {old_score} → {new_score}")
            return False

        # Dimension 2: Execution Efficiency Tie-Breakers (same score)
        old_filled = old_outcome.get('is_filled', False)
        new_filled = new_outcome.get('is_filled', False)
        old_metrics = old_outcome.get('trade_execution_metrics', {})
        new_metrics = new_outcome.get('trade_execution_metrics', {})

        # Tie-breaker A: MAE Stress Reduction (only when BOTH trades were physically filled)
        if old_filled and new_filled:
            old_mae = float(old_metrics.get('mae_stress_level_pct', 100.0))
            new_mae = float(new_metrics.get('mae_stress_level_pct', 100.0))

            if old_mae > self.cfg.mae_significance_threshold and (old_mae - new_mae) >= self.cfg.mae_improvement_threshold:
                logger.info(f"[REFINEMENT] MAE tiebreak | {old_mae}% → {new_mae}%")
                return True

        # Tie-breaker B: Capital Velocity (Time Efficiency)
        old_time = float(old_metrics.get('actual_holding_hours', 1000.0))
        new_time = float(new_metrics.get('actual_holding_hours', 1000.0))

        if new_res == "TP_HIT" and (old_time - new_time) >= self.cfg.time_improvement_threshold:
            logger.info(f"[REFINEMENT] time efficiency | {old_time}h → {new_time}h")
            return True

        logger.info(f"[STABLE] score {old_score} == {new_score}")
        return False
