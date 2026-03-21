import os
import sys
import json
import yaml
import argparse
import logging
from typing import Dict, Any, List

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

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

def apply_to_prompt(report_data: Dict[str, Any], prompt_path: str):
    """Applies master_prompt_patch from report to the specified prompt file."""
    analysis = report_data.get("analysis", {})
    patch_list = analysis.get("master_prompt_patch", [])
    
    if not patch_list:
        logger.info("No master_prompt_patch found in the report. Skipping prompt update.")
        return

    if not os.path.exists(prompt_path):
        logger.error(f"Prompt file not found: {prompt_path}")
        return

    with open(prompt_path, 'r', encoding='utf-8') as f:
        base_text = f.read()

    new_text = apply_patches(base_text, patch_list)

    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    
    logger.info(f"Successfully applied {len(patch_list)} patches to {prompt_path}")

def apply_to_config(report_data: Dict[str, Any], config_path: str):
    """
    (Placeholder/Extension) Applies config-related patches if present. 
    Currently focuses on the prompt, but can be extended if Coach starts 
    recommending specific YAML changes in a structured way.
    """
    analysis = report_data.get("analysis", {})
    config_patch = analysis.get("config_patch", {}) # Future proofing
    
    if not config_patch:
        return

    logger.info(f"Found config_patch in report. Note: Automatic config patching is not yet fully implemented.")
    # Implementation for YAML patching would go here

def main():
    parser = argparse.ArgumentParser(description="Manually apply a Coach Report patch to the trading system.")
    parser.add_argument("report_filename", help="Filename of the coach report (or full path).")
    
    args = parser.parse_args()

    # Determine project root relative to this script (src/agent/apply_coach_patch.py)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    config_path = os.path.join(project_root, "config", "config.yaml")

    # 1. Load Config early to resolve directories
    try:
        if not os.path.exists(config_path):
            logger.error(f"Config file not found at {config_path}")
            return
            
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Strict existence check for required keys
        paths_config = config['paths']
        coach_dir = paths_config['coach_dir']
        prompts_dir = paths_config['prompts_dir']
        trader_prompt_file = paths_config['prompt_trader_filename']
        
        input_report = args.report_filename
        
        # If it's just a filename, prepend coach_dir
        if not os.path.dirname(input_report):
            report_path = os.path.join(project_root, coach_dir, input_report)
        else:
            report_path = input_report

        # Resolve Prompt Path using config filename
        prompt_path = os.path.join(project_root, prompts_dir, trader_prompt_file)
        
    except KeyError as e:
        logger.error(f"Config is missing required key: {e}. Please update config.yaml.")
        return
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    # 2. Check and Load Report
    if not os.path.exists(report_path):
        logger.error(f"Report file not found: {report_path}")
        return

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load report from {report_path}: {e}")
        return

    logger.info(f"--- Applying Coach Patch from {os.path.basename(report_path)} ---")
    
    # 3. Apply to Prompt
    apply_to_prompt(report_data, prompt_path)
    
    # 4. Apply to Config (Future proofing)
    apply_to_config(report_data, config_path)

    logger.info("Done.")

if __name__ == "__main__":
    main()
