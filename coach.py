import os
import sys
import json
import logging
import argparse
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Path normalization for internal imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.coach_agent import CoachAgent
from src.utils.agent_utils import load_config, load_global_config
from src.utils.json_utils import save_json, load_json
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root

# Load environment variables
load_dotenv()

class CoachOrchestrator:
    """
    Orchestrates the strategic coaching session with physical archival.
    Fetches fresh forensic audits, invokes the Coach Agent, 
    archives patches, and moves processed sources to history.
    """
    def __init__(self, data_root: str):
        self.config = load_config()
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.api_key = os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
            
        self.coach = CoachAgent(self.config, api_key=self.api_key)
        self.logger = setup_logger("CoachOrchestrator", log_level=logging.INFO)

    def execute_pipeline(self, symbol: str, batch_size: Optional[int] = None):
        """
        Executes the full coaching workflow: Fetch -> Analyze -> Patch -> Archive.
        """
        self.logger.info(f"=== Starting Coaching Pipeline for {symbol} ===")
        
        # 1. Setup Directories
        review_dir = os.path.join(self.data_root, "reviewers")
        archive_dir = os.path.join(review_dir, "archived")
        os.makedirs(archive_dir, exist_ok=True)

        # 2. Fetch Historical Forensic Audits (Only from Root, ignoring archived/patches)
        review_history, source_paths = self._fetch_review_history(symbol, batch_size, review_dir)
        
        if not review_history:
            self.logger.warning(f"No fresh forensic audits found for {symbol}. Coach is resting.")
            return

        # 3. Invoke Coach Agent for Systemic Analysis
        self.logger.info(f"Feeding {len(review_history)} valid reports to Coach for systemic diagnosis...")
        raw_analysis = self.coach.analyze(review_history)

        # 4. Archive the Strategic Patch & Move Sources
        if raw_analysis:
            # A. Save the patch proposal
            patch_path = self._archive_patch(symbol, raw_analysis, archive_dir)
            
            # B. Physical Archival of processed reviews
            if patch_path:
                self._archive_sources(source_paths, archive_dir)

    def _fetch_review_history(self, symbol: str, batch_size: Optional[int], review_dir: str):
        """Scans the root reviewers directory for fresh, non-premature audits."""
        if not os.path.exists(review_dir):
            return [], []

        # Only look at files in the root of review_dir (ignores subfolders)
        prefix = f"{symbol}_reviewers_"
        files = sorted([
            f for f in os.listdir(review_dir) 
            if f.endswith(".json") and f.startswith(prefix) and os.path.isfile(os.path.join(review_dir, f))
        ], reverse=True)

        if batch_size:
            files = files[:batch_size]

        history = []
        valid_source_paths = []
        
        for filename in files:
            file_path = os.path.join(review_dir, filename)
            data = load_json(file_path)
            if data:
                # Filter out premature stub reports
                market_outcome = data.get("market_outcome", {})
                trade_metrics = market_outcome.get("trade_execution_metrics") or {}
                
                if trade_metrics:
                    is_premature = trade_metrics.get("is_premature_audit", False)
                    tp_sl_status = trade_metrics.get("tp_sl_result", "NEITHER")
                    
                    if is_premature and tp_sl_status == "NEITHER":
                        self.logger.debug(f"Skipping pending trade (No training value): {filename}")
                        continue

                data["_source_file"] = filename
                history.append(data)
                valid_source_paths.append(file_path)
        
        return history, valid_source_paths

    def _archive_patch(self, symbol: str, raw_analysis: str, output_dir: str) -> Optional[str]:
        """Standardizes and saves the systemic coaching patch."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_patches_{ts}.json"
        patch_path = os.path.join(output_dir, filename)

        try:
            analysis_data = json.loads(raw_analysis)
            
            # Handle potential nested analysis object from AI
            if "analysis" in analysis_data and len(analysis_data) == 1:
                analysis_data = analysis_data["analysis"]

            final_record = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "strategic_analysis": analysis_data
            }
            
            save_json(final_record, patch_path)
            self.logger.info(f"Coach Patch Proposal archived: {patch_path}")
            return patch_path
            
        except json.JSONDecodeError:
            self.logger.error("Coach Agent returned invalid JSON. Archiving raw text as fallback.")
            txt_path = patch_path.replace(".json", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(raw_analysis)
            self.logger.info(f"Raw analysis saved to {txt_path}")
            return txt_path

    def _archive_sources(self, source_paths: List[str], archive_dir: str):
        """Moves processed source files to the archived folder."""
        for file_path in source_paths:
            try:
                dest_path = os.path.join(archive_dir, os.path.basename(file_path))
                shutil.move(file_path, dest_path)
            except Exception as e:
                self.logger.error(f"Failed to archive source {file_path}: {e}")
        
        self.logger.info(f"Archived {len(source_paths)} processed reports to {archive_dir}.")

def main():
    parser = argparse.ArgumentParser(description="Strategic Trading Coach (Agent C)")
    parser.add_argument("--symbol", type=str, help="Symbol to analyze.")
    parser.add_argument("--data_root", type=str, required=True, help="Data directory root.")
    parser.add_argument("--batch", type=int, help="Limit number of recent reviews to analyze.")
    args = parser.parse_args()
    
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    if not symbol:
        print("Error: Symbol not provided and no default found in global_config.yaml")
        sys.exit(1)

    try:
        orchestrator = CoachOrchestrator(data_root=args.data_root)
        orchestrator.execute_pipeline(symbol=symbol, batch_size=args.batch)
    except Exception as e:
        print(f"Coaching Pipeline Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
