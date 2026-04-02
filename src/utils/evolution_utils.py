import os
import re
import yaml
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("EvolutionUtils")

class ConfigPatcher:
    """Handles deep YAML configuration merging for the Evolver."""
    
    @staticmethod
    def apply_patch(target_path: str, patch_overlays: Dict[str, Any]) -> bool:
        """Applies a specific parameter overlay to the strategy config."""
        if not patch_overlays or not os.path.exists(target_path):
            return False

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # Map evolution-friendly keys to their physical config nodes
            # e.g., 'high_volatility' targets 'regime_parameters' with specific context
            modified = False
            
            # Simple direct merge for now (v4.0 approach)
            # The patch_overlays should target top-level keys like 'regime_parameters'
            for key, val in patch_overlays.items():
                if key in config and isinstance(config[key], dict) and isinstance(val, dict):
                    config[key].update(val)
                    modified = True
                else:
                    # Top-level direct override
                    config[key] = val
                    modified = True

            if modified:
                with open(target_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, sort_keys=False, default_flow_style=False)
                return True
            return False
            
        except Exception as e:
            logger.error(f"ConfigPatcher: Failed to apply patch to {target_path}: {e}")
            return False

class PromptDistiller:
    """Handles granular distillation of agent instructions in Markdown files."""
    
    @staticmethod
    def apply_distillation(target_path: str, distillation: Dict[str, str]) -> bool:
        """Replaces old high-entropy text with new distilled logic."""
        old_text = distillation.get("old_text")
        new_text = distillation.get("new_distilled_law")
        
        if not old_text or not new_text or not os.path.exists(target_path):
            return False

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_text in content:
                new_content = content.replace(old_text, new_text)
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return True
            
            # Flexible Match Recovery (Regex)
            escaped_old = re.escape(old_text)
            flexible_pattern = re.sub(r'\\\s+', r'\\s+', escaped_old)
            if re.search(flexible_pattern, content):
                new_content = re.sub(flexible_pattern, new_text, content, count=1)
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"PromptDistiller: Failed to distill {target_path}: {e}")
            return False
