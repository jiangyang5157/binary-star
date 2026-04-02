import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import datetime

from src.utils.pipeline_utils import safe_format
from src.utils.path_utils import resolve_project_root

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class ReviewerConfig:
    """Dataclass for type-safe Reviewer configuration."""
    macro_interval: str
    micro_interval: str
    strategy_intent: str
    regime_anchor_drift_threshold: float
    performance_knobs: Dict[str, Any]
    forensic_parameters: Dict[str, Any]

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "ReviewerConfig":
        """Factory method for strategic config."""
        sampling = cfg['sampling_parameters']
        topography = cfg['topography_parameters']
        regime = cfg['regime_parameters']
        perf_knobs = cfg['performance_evaluation_knobs']
        forensic = cfg['forensic_parameters']
        
        return cls(
            macro_interval=str(sampling['macro_context']['time_interval']),
            micro_interval=str(sampling['micro_context']['time_interval']),
            strategy_intent=str(cfg.get('strategy_intent', "")),
            regime_anchor_drift_threshold=float(regime['anchor_drift_threshold']),
            performance_knobs=perf_knobs,
            forensic_parameters=forensic
        )

class ReviewerAgent:
    """
    The Post-Execution Forensic Data Reporter (The Reviewer).
    
    Now a purely deterministic component that aggregates trade execution 
    metrics and market snapshots. AI-driven audit reasoning is deferred 
    to the Batch Coaching/Evolver phase.
    """
    def __init__(self, config: ReviewerConfig):
        """
        Initializes the Reviewer with historical and tactical configurations.
        """
        self.config = config

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None,
               visual_context: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Assembles a deterministic forensic audit of a trading session.
        
        Args:
            historical_strategy: The full triad session (Draft, Critique, Final).
            actual_outcome: The PnL, TP/SL status, and execution metrics.
            current_observation: The market data at the time of review.
            visual_context: Dictionary of historical/current chart snapshots.
            
        Returns:
            A structured dictionary containing aggregated forensic results.
        """
        logger.info(f"Reviewer: Assembling deterministic forensic report...")
        
        # In a deterministic world, we "Pass" the findings as a structured data dump.
        # The AI-driven evaluation_score and post_mortem are deferred.
        review_result = {
            "evaluation_score": 0, # Pending Batch Coach
            "adversarial_audit": {
                "protocol_breach": "PENDING_OFFLINE_COACH",
                "shadow_evidence": [],
                "hallucination_detected": False
            },
            "post_mortem": "System Status: Architecture Stabilized. Real-time AI audit deferred to Coaches.",
            "metrics_summary": actual_outcome.get("trade_execution_metrics", {})
        }
        
        # Inject Audit Fingerprint for Chain of Custody
        project_root = resolve_project_root()
        config_path = os.path.join(project_root, 'config', 'strategy_config.yaml')
        
        review_result["audit_metadata"] = {
            "config_hash": get_file_hash(config_path),
            "audit_timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        return review_result
