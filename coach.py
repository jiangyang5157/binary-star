import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Path normalization for internal imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.coach_agent import CoachAgent
from src.utils.agent_utils import load_config
from src.utils.json_utils import save_json, load_json
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root

# Load environment variables
load_dotenv()

class CoachOrchestrator:
    """
    Orchestrates the strategic coaching session.
    Fetches historical forensic audits, invokes the Coach Agent, 
    and archives the systemic analysis reports.
    """
    def __init__(self, data_root: str = "data"):
        self.config = load_config()
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.api_key = os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
            
        self.coach = CoachAgent(self.config, api_key=self.api_key)
        self.logger = setup_logger("CoachOrchestrator", log_level=logging.INFO)

    def execute_pipeline(self, symbol: str, batch_size: Optional[int] = None):
        """
        Executes the full coaching workflow for a specific symbol.
        """
        self.logger.info(f"=== Starting Coaching Pipeline for {symbol} ===")
        
        # 1. Fetch Historical Forensic Audits
        review_history = self._fetch_review_history(symbol, batch_size)
        if not review_history:
            self.logger.warning(f"No forensic audits found for {symbol}. Sidestepping.")
            return

        # 2. Invoke Coach Agent for Systemic Analysis
        raw_analysis = self.coach.analyze(review_history)

        # 3. Archive the Strategic Report
        self._archive_report(symbol, review_history, raw_analysis)

    def _fetch_review_history(self, symbol: str, batch_size: Optional[int]) -> List[Dict[str, Any]]:
        """Scans the data directory for the latest forensic audits."""
        reviews_dir = os.path.join(self.data_root, "reviewers")
        if not os.path.exists(reviews_dir):
            return []

        # New standardized naming convention: SYMBOL_reviewers_YYYYMMDD_HHMMSS.json
        prefix = f"{symbol}_reviewers_"
        files = sorted([
            f for f in os.listdir(reviews_dir) 
            if f.endswith(".json") and f.startswith(prefix)
        ], reverse=True)

        if batch_size:
            files = files[:batch_size]

        history = []
        for filename in files:
            data = load_json(os.path.join(reviews_dir, filename))
            if data:
                history.append(data)
        
        return history

    def _archive_report(self, symbol: str, review_history: List[Dict[str, Any]], raw_analysis: str):
        """Standardizes and saves the systemic coaching report."""
        coaches_dir = os.path.join(self.data_root, "coaches")
        os.makedirs(coaches_dir, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        # Requested format: SYMBOL_coaches_YYYYMMDD_HHMMSS.json
        filename = f"{symbol}_coaches_{ts}.json"
        report_path = os.path.join(coaches_dir, filename)

        try:
            analysis_data = json.loads(raw_analysis)
            
            # Handle potential nested analysis object from AI
            if "analysis" in analysis_data and len(analysis_data) == 1:
                analysis_data = analysis_data["analysis"]

            final_record = {
                "coach_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "sample_size": len(review_history),
                "strategic_analysis": analysis_data
            }
            
            save_json(final_record, report_path)
            self.logger.info(f"Strategic Coach Report archived: {report_path}")
            
        except json.JSONDecodeError:
            self.logger.error("Coach Agent returned invalid JSON. Archiving raw text as fallback.")
            txt_path = report_path.replace(".json", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(raw_analysis)
            self.logger.info(f"Raw analysis saved to {txt_path}")

def main():
    parser = argparse.ArgumentParser(description="Strategic Trading Coach (Agent C)")
    parser.add_argument("--symbol", type=str, required=True, help="Symbol to analyze.")
    parser.add_argument("--batch", type=int, default=5, help="Number of recent reviews to analyze.")
    parser.add_argument("--data_root", type=str, default="data", help="Data directory root.")
    args = parser.parse_args()

    try:
        orchestrator = CoachOrchestrator(data_root=args.data_root)
        orchestrator.execute_pipeline(symbol=args.symbol, batch_size=args.batch)
    except Exception as e:
        print(f"Coaching Pipeline Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
