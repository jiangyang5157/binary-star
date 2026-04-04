import os
import re
import logging
from typing import Dict, Any, List, Optional
from ruamel.yaml import YAML

logger = logging.getLogger("EvolutionUtils")

class ConfigPatcher:
    """Handles deep YAML configuration merging with comment preservation."""
    
    @staticmethod
    def apply_patch(target_path: str, patch_overlays: Dict[str, Any]) -> bool:
        """Applies a specific parameter overlay with deterministic nested search."""
        if not patch_overlays or not os.path.exists(target_path):
            return False

        try:
            yaml = YAML()
            yaml.preserve_quotes = True
            yaml.indent(mapping=2, sequence=4, offset=2)
            
            with open(target_path, 'r', encoding='utf-8') as f:
                config = yaml.load(f)

            def find_and_update_recursive(source, key, value):
                """Search whole tree for a key and update it."""
                if key in source:
                    if isinstance(source[key], dict) and isinstance(value, dict):
                        source[key].update(value)
                    else:
                        source[key] = value
                    return True
                
                for k, v in source.items():
                    if isinstance(v, dict):
                        if find_and_update_recursive(v, key, value):
                            return True
                return False

            modified = False
            for k, v in patch_overlays.items():
                if find_and_update_recursive(config, k, v):
                    modified = True
                else:
                    # Not found anywhere? Add to root.
                    config[k] = v
                    modified = True

            if modified:
                with open(target_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f)
                return True
            return False
            
        except Exception as e:
            logger.error(f"ConfigPatcher: Failed to apply patch to {target_path}: {e}")
            return False

class PromptDistiller:
    """Handles granular distillation of agent instructions in Markdown files."""
    
    @staticmethod
    def apply_distillation(target_path: str, anchor: str, new_text: str) -> bool:
        """Replaces old high-entropy text with new distilled logic (Hardened)."""
        if not anchor or not new_text or not os.path.exists(target_path):
            return False

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Strategy: Collapse all anchor whitespace into a flexible pattern
            # 1. Simplify anchor whitespace
            clean_anchor = re.sub(r'[\s\n\r\t]+', ' ', anchor).strip()
            # 2. Escape regex meta-characters
            pattern = re.escape(clean_anchor)
            # 3. Replace escaped spaces '\ ' (Python 3.9+) with [\s\r\n\t]+
            # If for some reason re.escape didn't escape space, we handle that too
            pattern = pattern.replace(r'\ ', r'[\s\r\n\t]+').replace(' ', r'[\s\r\n\t]+')
            
            if re.search(pattern, content):
                new_content = re.sub(pattern, new_text, content, count=1)
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"PromptDistiller: Failed to distill {target_path}: {e}")
            return False
