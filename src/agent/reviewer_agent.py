import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import datetime
from google import genai
from google.genai import types

from src.agent.base_agent import BaseAgent
from src.utils.agent_utils import read_prompt_template, safe_format
from src.utils.path_utils import resolve_project_root
from src.utils.json_utils import extract_json_from_text

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

@dataclass(frozen=True)
class ReviewerConfig:
    """Dataclass for type-safe Reviewer configuration."""
    model: str
    model_temperature: float
    role_prompt_path: str
    strategist_prompt_path: str
    critic_prompt_path: str
    macro_interval: str
    micro_interval: str
    strategy_intent: str
    stop_loss_buffer_max: float
    score_mae_pinpoint_limit: float
    score_mae_standard_limit: float
    score_mae_logic_failure_limit: float
    score_mfe_optimal_upper: float
    score_mfe_optimal_lower: float
    score_mfe_acceptable_limit: float
    score_opportunity_cost_limit: float
    score_opportunity_cost_catastrophe_limit: float
    score_opportunity_cost_catastrophe_floor: int
    score_time_efficiency_limit: float
    penalty_compliance_breach: float
    point_base_tp_hit: int
    point_base_sl_hit: int
    point_base_neutral_valid: int
    point_penalty_opportunity_cost: int
    point_penalty_logic_failure: int
    point_penalty_mfe_premature_base: int
    point_penalty_temporal_failure: int
    point_penalty_stophunt_blindness: int
    point_bonus_structural_insight: int
    score_mae_extra_buffer: float
    score_frontrun_leniency_pct: int
    holding_time_modifier: float
    point_bonus_optimal_capture: int
    score_missed_opportunity_base: float
    regime_anchor_drift_threshold: float
    max_tool_iterations: int

    @classmethod
    def from_dict(cls, rev_cfg: Dict[str, Any], strat_cfg: Dict[str, Any], crit_cfg: Dict[str, Any], obs_cfg: Dict[str, Any], shared_cfg: Dict[str, Any], strategy_intent: str) -> "ReviewerConfig":
        """Factory method to extract reviewer config from decoupled components."""
        project_root = resolve_project_root()
        return cls(
            model=str(rev_cfg['model']),
            model_temperature=float(rev_cfg['model_temperature']),
            role_prompt_path=os.path.join(project_root, rev_cfg['role_definition_prompt']),
            strategist_prompt_path=os.path.join(project_root, strat_cfg['role_definition_prompt']),
            critic_prompt_path=os.path.join(project_root, crit_cfg['role_definition_prompt']),
            macro_interval=str(obs_cfg['macro_analysis_context']['time_interval']),
            micro_interval=str(obs_cfg['micro_analysis_context']['time_interval']),
            strategy_intent=strategy_intent,
            stop_loss_buffer_max=float(strat_cfg['stop_loss_buffer_max']),
            score_mae_pinpoint_limit=float(rev_cfg['score_mae_pinpoint_limit']),
            score_mae_standard_limit=float(rev_cfg['score_mae_standard_limit']),
            score_mae_logic_failure_limit=float(rev_cfg['score_mae_logic_failure_limit']),
            score_mfe_optimal_upper=float(rev_cfg['score_mfe_optimal_upper']),
            score_mfe_optimal_lower=float(rev_cfg['score_mfe_optimal_lower']),
            score_mfe_acceptable_limit=float(rev_cfg['score_mfe_acceptable_limit']),
            score_opportunity_cost_limit=float(rev_cfg['score_opportunity_cost_limit']),
            score_opportunity_cost_catastrophe_limit=float(rev_cfg['score_opportunity_cost_catastrophe_limit']),
            score_opportunity_cost_catastrophe_floor=int(rev_cfg['score_opportunity_cost_catastrophe_floor']),
            score_time_efficiency_limit=float(rev_cfg['score_time_efficiency_limit']),
            penalty_compliance_breach=float(rev_cfg['penalty_compliance_breach']),
            point_base_tp_hit=int(rev_cfg['point_base_tp_hit']),
            point_base_sl_hit=int(rev_cfg['point_base_sl_hit']),
            point_base_neutral_valid=int(rev_cfg['point_base_neutral_valid']),
            point_penalty_opportunity_cost=int(rev_cfg['point_penalty_opportunity_cost']),
            point_penalty_logic_failure=int(rev_penalty_logic_failure := rev_cfg['point_penalty_logic_failure']),
            point_penalty_mfe_premature_base=int(rev_cfg['point_penalty_mfe_premature_base']),
            point_penalty_temporal_failure=int(rev_cfg['point_penalty_temporal_failure']),
            point_penalty_stophunt_blindness=int(rev_cfg['point_penalty_stophunt_blindness']),
            point_bonus_structural_insight=int(rev_cfg['point_bonus_structural_insight']),
            score_mae_extra_buffer=float(rev_cfg['score_mae_extra_buffer']),
            score_frontrun_leniency_pct=int(rev_cfg['score_frontrun_leniency_pct']),
            holding_time_modifier=float(strat_cfg['holding_time_modifier']),
            point_bonus_optimal_capture=int(rev_cfg['point_bonus_optimal_capture']),
            score_missed_opportunity_base=float(rev_cfg['score_missed_opportunity_base']),
            regime_anchor_drift_threshold=float(obs_cfg['regime_anchor_drift_threshold']),
            max_tool_iterations=int(shared_cfg['max_tool_iterations'])
        )

class ReviewerAgent(BaseAgent):
    """
    The Post-Execution Forensic Analyst (The Reviewer).
    
    This agent analyzes historical simulated trades, comparing the 
    forecasted reasoning of the triad against the actual price action outcomes. 
    It assigns scores and generates the 'Review Summary' for batch coaching.
    """
    def __init__(
        self, 
        config: ReviewerConfig, 
        api_timeout: int,
        retry_count: int,
        retry_multiplier: float,
        retry_min: int,
        retry_max: int,
        ai_client: genai.Client
    ):
        """
        Initializes the Reviewer with a pre-assembled type-safe configuration.
        """
        self.config = config
        super().__init__(
            model=self.config.model,
            temperature=self.config.model_temperature,
            ai_client=ai_client,
            max_tool_iterations=self.config.max_tool_iterations,
            api_timeout=api_timeout,
            retry_count=retry_count,
            retry_multiplier=retry_multiplier,
            retry_min=retry_min,
            retry_max=retry_max
        )

    def review(self, historical_strategy: Dict[str, Any], 
               actual_outcome: Dict[str, Any],
               current_observation: Optional[Dict[str, Any]] = None,
               visual_context: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Executes a multimodal post-mortem audit of a historical trading session.
        
        Args:
            historical_strategy: The full triad session (Draft, Critique, Final).
            actual_outcome: The PnL, TP/SL status, and execution metrics.
            current_observation: The market data at the time of review.
            visual_context: Dictionary of historical/current chart snapshots.
            
        Returns:
            A structured dictionary containing the forensic audit results.
        """
        logger.info(f"Reviewer: Auditing historical strategy session...")
        prompt_text = self._build_prompt(historical_strategy, actual_outcome, current_observation)
        
        # Build multimodal payload with forensic visual evidence
        contents = [prompt_text]
        if visual_context:
            labels = {
                "t0_macro": "T0 Historical Macro Snapshot",
                "t0_micro": "T0 Historical Micro Snapshot",
                "t1_macro": "T1 Current Macro Snapshot",
                "t1_micro": "T1 Current Micro Snapshot"
            }
            
            for key, path in visual_context.items():
                label = labels.get(key, f"Visual Supplement: {key}")
                if path:
                    # Resolve to absolute path for reliable reading across environments
                    if not os.path.isabs(path):
                        abs_path = os.path.join(resolve_project_root(), path)
                    else:
                        abs_path = path
                        
                    if os.path.exists(abs_path):
                        logger.info(f"Reviewer: Attaching forensic evidence: {label} ({abs_path})")
                        with open(abs_path, "rb") as f:
                            image_bytes = f.read()
                            contents.append(f"\n{label}")
                            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
                    else:
                        contents.append(f"\n[SYSTEM NOTICE: Forensic visual asset '{label}' missing from storage.]")
                else:
                    contents.append(f"\n[SYSTEM NOTICE: Forensic visual asset '{label}' missing from storage.]")

        # Execute high-fidelity review cycle via BaseAgent
        review_result = self._execute_ai_cycle(contents, agent_name="Reviewer")
        
        # Inject Audit Fingerprint for Chain of Custody
        from src.utils.agent_utils import get_file_hash
        project_root = resolve_project_root()
        config_path = os.path.join(project_root, 'config', 'agent_config.yaml')
        observer_path = os.path.join(os.path.dirname(self.config.role_prompt_path), 'observer.md')
        
        review_result["audit_metadata"] = {
            "reviewer_hash": get_file_hash(self.config.role_prompt_path),
            "observer_hash": get_file_hash(observer_path),
            "config_hash": get_file_hash(config_path),
            "audit_timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        return review_result

    def _build_prompt(self, strategy: Dict[str, Any], 
                      outcome: Dict[str, Any], 
                      observation: Optional[Dict[str, Any]]) -> str:
        """
        Constructs the high-context review prompt by injecting the full triad history.
        """
        # Load linked agent prompts for semantic ground-truth context
        strategist_prompt = read_prompt_template(self.config.strategist_prompt_path)
        critic_prompt = read_prompt_template(self.config.critic_prompt_path)
        
        # Prepare context data
        context = {
            "historical_observation": json.dumps(strategy.get("observation"), indent=2, ensure_ascii=False),
            "draft_plan": json.dumps(strategy.get("draft"), indent=2, ensure_ascii=False),
            "critique_against_draft_plan": json.dumps(strategy.get("critique"), indent=2, ensure_ascii=False),
            "final_decision": json.dumps(strategy.get("final_decision"), indent=2, ensure_ascii=False),
            "actual_outcome_metrics": json.dumps(outcome, indent=2, ensure_ascii=False),
            "current_observation": json.dumps(observation, indent=2, ensure_ascii=False) if observation else "N/A",
            "strategist_prompt": strategist_prompt,
            "critic_prompt": critic_prompt,
            "strategy_intent": self.config.strategy_intent,
            "macro_interval": self.config.macro_interval,
            "micro_interval": self.config.micro_interval,
            "execution_timeframe": self.config.micro_interval,
            "stop_loss_buffer_max": self.config.stop_loss_buffer_max,
            "score_mae_pinpoint_limit": self.config.score_mae_pinpoint_limit,
            "score_mae_standard_limit": self.config.score_mae_standard_limit,
            "score_mae_logic_failure_limit": self.config.score_mae_logic_failure_limit,
            "score_mfe_optimal_upper": self.config.score_mfe_optimal_upper,
            "score_mfe_optimal_lower": self.config.score_mfe_optimal_lower,
            "score_mfe_acceptable_limit": self.config.score_mfe_acceptable_limit,
            "score_opportunity_cost_limit": self.config.score_opportunity_cost_limit,
            "score_opportunity_cost_catastrophe_limit": self.config.score_opportunity_cost_catastrophe_limit,
            "score_opportunity_cost_catastrophe_floor": self.config.score_opportunity_cost_catastrophe_floor,
            "score_time_efficiency_limit": self.config.score_time_efficiency_limit,
            "penalty_compliance_breach": self.config.penalty_compliance_breach,
            "point_base_tp_hit": self.config.point_base_tp_hit,
            "point_base_sl_hit": self.config.point_base_sl_hit,
            "point_base_neutral_valid": self.config.point_base_neutral_valid,
            "point_penalty_opportunity_cost": self.config.point_penalty_opportunity_cost,
            "point_penalty_logic_failure": self.config.point_penalty_logic_failure,
            "point_penalty_mfe_premature_base": self.config.point_penalty_mfe_premature_base,
            "point_penalty_temporal_failure": self.config.point_penalty_temporal_failure,
            "point_penalty_stophunt_blindness": self.config.point_penalty_stophunt_blindness,
            "point_bonus_structural_insight": self.config.point_bonus_structural_insight,
            "score_mae_extra_buffer": self.config.score_mae_extra_buffer,
            "score_frontrun_leniency_pct": self.config.score_frontrun_leniency_pct,
            "holding_time_modifier": self.config.holding_time_modifier,
            "point_bonus_optimal_capture": self.config.point_bonus_optimal_capture,
            "score_missed_opportunity_base": self.config.score_missed_opportunity_base,
            "regime_anchor_drift_threshold": self.config.regime_anchor_drift_threshold
        }
        
        return self._prepare_prompt(self.config.role_prompt_path, **context)
