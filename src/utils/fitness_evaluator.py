import logging
from typing import Dict, Any

logger = logging.getLogger("FitnessEvaluator")


class FitnessEvaluator:
    """
    Darwinian Fitness Evaluator (v3.1)
    
    A shared, stateless judge that scores market outcomes and compares 
    old vs. new strategy results for the Evolution pipeline.
    
    Used by:
      - EvolverSandbox (online shadow replay)
      - sandbox_review.py (offline re-evaluation)
    """

    def __init__(self, config_dict: Dict[str, Any]):
        """
        Args:
            config_dict: The combined system configuration (global + strategy).
                         Reads thresholds from the 'sandbox' block.
        """
        self.config_dict = config_dict

    def get_fitness_score(self, outcome: Dict[str, Any]) -> float:
        """
        Calculates a composite forensic fitness score for a single market outcome.
        Standardizes calculations by sourcing weights from the sandbox config.

        Representative Score Ladder (Default Config):
          TP_HIT (clean, fast):              100
          TP_HIT (clean, slow >48h):          85
          NEUTRAL (justified surrender):      75
          NEUTRAL (baseline):                 60
          TP_HIT (LOGIC_FAILURE):             45
          NEITHER (baseline, unfilled):       40
          NEITHER (catastrophic miss):        20
          SL_HIT (clean):                     15
          SL_HIT (LOGIC_FAILURE):            -25
        """
        res = str(outcome.get('tp_sl_result', 'N/A')).upper()
        is_filled = outcome.get('is_filled', False)
        metrics = outcome.get('trade_execution_metrics', {})
        verdict = outcome.get('forensic_verdict', {})

        # --- 1. Load Sandbox Config ---
        sandbox_cfg = self.config_dict.get('sandbox', {})
        cfg_base = sandbox_cfg.get('base_scores', {})
        cfg_mods = sandbox_cfg.get('modifiers', {})

        # --- 2. Base PnL Score ---
        # Map YAML keys (lowercase) to result strings (uppercase)
        base_scores = {
            "TP_HIT": float(cfg_base.get('tp_hit', 100.0)),
            "NEUTRAL": float(cfg_base.get('neutral', 60.0)),
            "NEITHER": float(cfg_base.get('neither', 40.0)),
            "SL_HIT": float(cfg_base.get('sl_hit', 15.0)),
            "N/A": float(cfg_base.get('na', 0.0))
        }
        score = base_scores.get(res, 0.0)

        # --- 3. Execution Quality Penalty (ALL filled trades) ---
        if is_filled:
            mae_tier = str(metrics.get('mae_stress_tier', '')).upper()
            mae_pct = float(metrics.get('mae_stress_level_pct', 0.0))
            hours = float(metrics.get('actual_hours', 0.0))

            # LOGIC_FAILURE or MAE >= 100%: Structural defense collapsed
            if mae_tier == "LOGIC_FAILURE" or mae_pct >= 100.0:
                score += float(cfg_mods.get('logic_failure_penalty', -40.0))
            elif mae_tier == "LUCK":
                score += float(cfg_mods.get('luck_penalty', -20.0))

            # Slow capital lock penalty (only for directional trades)
            if res in ("TP_HIT", "NEITHER") and hours > 48.0:
                score += float(cfg_mods.get('slow_lock_penalty', -15.0))

        # --- 4. Forensic Verdict Modifiers ---
        # Smart Surrender: Disciplined inaction in a dead market
        if verdict.get('is_justified_surrender') is True:
            score += float(cfg_mods.get('smart_surrender_bonus', 15.0))

        # Catastrophic Miss: Directional opinion correct, but order never filled
        if verdict.get('is_catastrophic_miss') is True:
            score += float(cfg_mods.get('catastrophic_miss_penalty', -20.0))

        return score


    def is_superior(self, old_outcome: Dict[str, Any], new_outcome: Dict[str, Any]) -> bool:
        """
        Darwinian Comparison (v3.1): Evaluates PnL, forensic intelligence, 
        and execution efficiency.
        
        Returns True if the new outcome is strictly better than the old one.
        """
        old_score = self.get_fitness_score(old_outcome)
        new_score = self.get_fitness_score(new_outcome)

        old_res = str(old_outcome.get('tp_sl_result', 'N/A')).upper()
        new_res = str(new_outcome.get('tp_sl_result', 'N/A')).upper()

        # Dimension 1: Absolute Fitness Resolution
        if new_score > old_score:
            logger.info(f"[IMPROVEMENT] Darwinian score: {old_score} -> {new_score} ({old_res} -> {new_res})")
            return True
        if new_score < old_score:
            logger.info(f"[NO_IMPROVEMENT] Darwinian score: {old_score} -> {new_score} ({old_res} -> {new_res})")
            return False

        # Dimension 2: Execution Efficiency Tie-Breakers (same score)
        sandbox_cfg = self.config_dict.get('sandbox', {})
        old_filled = old_outcome.get('is_filled', False)
        new_filled = new_outcome.get('is_filled', False)
        old_metrics = old_outcome.get('trade_execution_metrics', {})
        new_metrics = new_outcome.get('trade_execution_metrics', {})

        # Tie-breaker A: MAE Stress Reduction (only when BOTH trades were physically filled)
        if old_filled and new_filled:
            old_mae = float(old_metrics.get('mae_stress_level_pct', 100.0))
            new_mae = float(new_metrics.get('mae_stress_level_pct', 100.0))

            mae_sig = float(sandbox_cfg.get('mae_significance_threshold', 15.0))
            mae_imp = float(sandbox_cfg.get('mae_improvement_threshold', 5.0))

            if old_mae > mae_sig and (old_mae - new_mae) >= mae_imp:
                logger.info(f"[REFINEMENT] MAE tiebreak: {old_mae}% -> {new_mae}%")
                return True

        # Tie-breaker B: Capital Velocity (Time Efficiency)
        old_time = float(old_metrics.get('actual_hours', 1000.0))
        new_time = float(new_metrics.get('actual_hours', 1000.0))
        
        time_imp = float(sandbox_cfg.get('time_improvement_threshold'))
        
        if new_res == "TP_HIT" and (old_time - new_time) >= time_imp:
            logger.info(f"[REFINEMENT] Time efficiency: {old_time}h -> {new_time}h")
            return True

        logger.info(f"[STABLE] Darwinian score: {old_score} == {new_score} ({old_res} -> {new_res})")
        return False
