import os
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class PromptManager:
    """
    Handles dynamic prompt management and strategic logic patching.
    Bridges the gap between Agent C (Coach) and Agent A (Trader).
    """
    @staticmethod
    def apply_patches(base_text: str, patch_list: List[Dict[str, Any]]) -> str:
        """
        Applies a list of strategic patches to the base prompt text.
        Supported actions: ADD, REPLACE, REMOVE.
        """
        if not patch_list:
            return base_text

        patched_text = base_text
        for patch in patch_list:
            action = patch.get("action", "").upper()
            
            try:
                if action == "ADD":
                    # For ADD, we append content to a specific section header
                    target_section = patch.get("target_section", "")
                    content = patch.get("content", "")
                    if target_section in patched_text:
                        # Find the next section or end of file
                        logger.info(f"Applying ADD patch to section: {target_section}")
                        patched_text = patched_text.replace(target_section, f"{target_section}\n{content}")
                    else:
                        logger.warning(f"Target section '{target_section}' not found for ADD action. Appending to end.")
                        patched_text += f"\n\n{content}"

                elif action == "REPLACE":
                    target = patch.get("target", "")
                    replacement = patch.get("replacement", "")
                    if target and target in patched_text:
                        logger.info(f"Applying REPLACE patch for: {target[:30]}...")
                        patched_text = patched_text.replace(target, replacement)
                    else:
                        logger.warning(f"Target text for REPLACE not found.")

                elif action == "REMOVE":
                    target = patch.get("target", "")
                    if target and target in patched_text:
                        logger.info(f"Applying REMOVE patch for: {target[:30]}...")
                        patched_text = patched_text.replace(target, "")
                    else:
                        logger.warning(f"Target text for REMOVE not found.")
            
            except Exception as e:
                logger.error(f"Failed to apply patch {patch}: {e}")

        return patched_text

    @staticmethod
    def get_latest_coach_report(symbol: str, coach_dir: str) -> Dict[str, Any]:
        """
        Scans for the latest coach report for a given symbol.
        """
        if not os.path.exists(coach_dir):
            return {}

        prefix = f"coach_{symbol}_"
        reports = [f for f in os.listdir(coach_dir) if f.startswith(prefix) and f.endswith(".json")]
        if not reports:
            return {}

        # Sorting by filename (which includes timestamp) descending
        latest_report_file = sorted(reports, reverse=True)[0]
        report_path = os.path.join(coach_dir, latest_report_file)
        
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load coach report {report_path}: {e}")
            return {}

    def get_patched_prompt(self, base_prompt_path: str, symbol: str, coach_dir: str) -> str:
        """
        Returns the fully patched prompt text for a given symbol.
        """
        try:
            with open(base_prompt_path, 'r', encoding='utf-8') as f:
                base_text = f.read()
        except Exception as e:
            logger.error(f"Failed to read base prompt {base_prompt_path}: {e}")
            return ""

        report = self.get_latest_coach_report(symbol, coach_dir)
        if not report:
            logger.info(f"No coach report found for {symbol}. Using base prompt.")
            return base_text

        # Extract patch from the 'analysis' sub-object (matching coach_agent output)
        analysis = report.get("analysis", {})
        patch_list = analysis.get("master_prompt_patch", [])
        
        if not patch_list:
            logger.info(f"No prompt patches found in latest coach report for {symbol}.")
            return base_text

        logger.info(f"Applying {len(patch_list)} strategic patches from Agent C for {symbol}...")
        return self.apply_patches(base_text, patch_list)
