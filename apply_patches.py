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

def recursive_update(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively updates a dictionary."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            recursive_update(base[key], value)
        else:
            base[key] = value
    return base

def find_and_update_flat_key(base: Dict[str, Any], key: str, value: Any) -> bool:
    """Best-effort attempt to update a key that might be nested if not found at top level."""
    if key in base:
        base[key] = value
        return True
    for k, v in base.items():
        if isinstance(v, dict):
            if find_and_update_flat_key(v, key, value):
                return True
    return False

def apply_to_config(report_data: Dict[str, Any], config_path: str):
    """
    Applies master_config_update from report to the specified config YAML file.
    Supports both nested and flat key updates.
    """
    analysis = report_data.get("analysis", {})
    # Note: Coach prompt uses master_config_update
    config_update = analysis.get("master_config_update", {})
    
    if not config_update:
        logger.info("No master_config_update found in the report. Skipping config update.")
        return

    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            current_config = yaml.safe_load(f) or {}

        logger.info(f"Applying {len(config_update)} config updates...")
        
        for key, value in config_update.items():
            if isinstance(value, dict):
                # If it's a dict, use recursive update (assuming it follows structure)
                if key not in current_config:
                    current_config[key] = {}
                recursive_update(current_config[key], value)
            else:
                # If it's a flat value, try to find where it belongs
                if not find_and_update_flat_key(current_config, key, value):
                    logger.warning(f"Config key '{key}' not found in current structure. Adding as top-level.")
                    current_config[key] = value

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(current_config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        
        logger.info(f"Successfully updated config at {config_path}")

    except Exception as e:
        logger.error(f"Failed to apply config patch: {e}")

def main():
    parser = argparse.ArgumentParser(description="Apply a Coach Report patch to the trading system.")
    parser.add_argument("patch_filename", metavar="PATH", help="Path to the coach report")
    
    args = parser.parse_args()

    # Determine project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    config_path = "config/config.yaml"

    # 1. Load Config early to resolve directories
    try:
        if not os.path.exists(config_path):
            logger.error(f"Config file not found at {config_path}")
            return
            
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Strict existence check for required keys
        paths_config = config['paths']
        prompts_dir = paths_config['prompts_dir']
        trader_prompt_file = paths_config['prompt_predictor_filename']
        # Path to the patch file (e.g. data/raw/coach/report.json)
        report_path = args.patch_filename
        
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
