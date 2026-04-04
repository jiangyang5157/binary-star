import os
import re
import logging
import collections.abc
from typing import Dict, Any, List, Optional
from ruamel.yaml import YAML

logger = logging.getLogger("EvolutionUtils")

class ConfigPatcher:
    """Handles deep YAML configuration merging with comment preservation."""
    
    @staticmethod
    def apply_patch(target_path: str, key: str, value: Any, parent_path: str = "") -> int:
        """
        Applies a parameter overlay with precise path targeting or recursive search.
        Returns the number of keys updated.
        """
        if not key or not os.path.exists(target_path):
            return 0

        try:
            yaml = YAML()
            yaml.preserve_quotes = True
            yaml.indent(mapping=2, sequence=4, offset=2)
            
            with open(target_path, 'r', encoding='utf-8') as f:
                config = yaml.load(f)

            def find_and_update_recursive(source, k, v):
                count = 0
                if k in source:
                    # v6.11: Support both dict and CommentedMap (ruamel)
                    if isinstance(source[k], (dict, collections.abc.Mapping)) and isinstance(v, (dict, collections.abc.Mapping)):
                        source[k].update(v)
                    else:
                        source[k] = v
                    count += 1
                
                for node_k, node_v in source.items():
                    if isinstance(node_v, (dict, collections.abc.Mapping)):
                        count += find_and_update_recursive(node_v, k, v)
                return count

            def navigate_and_update(source, path_parts, k, v):
                if not path_parts:
                    # We reached the target segment
                    if k in source:
                        source[k] = v
                        return 1
                    # If key not in this segment, add it
                    source[k] = v
                    return 1
                
                current_segment = path_parts[0]
                if current_segment in source and isinstance(source[current_segment], (dict, collections.abc.Mapping)):
                    return navigate_and_update(source[current_segment], path_parts[1:], k, v)
                return 0

            update_count = 0
            if parent_path:
                # 1. Path-specific update (Precise)
                parts = parent_path.split('.')
                update_count = navigate_and_update(config, parts, key, value)
            elif key in config:
                # 2. Root Only (Strict)
                if isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value
                update_count = 1
            else:
                # 3. Key not in root and no path provided -> Skip and Warn
                logger.warning(f"ConfigPatcher: Key '{key}' not found at root level. Skipping.")
                return 0

            if update_count > 0:
                with open(target_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f)
                
            return update_count
            
        except Exception as e:
            logger.error(f"ConfigPatcher: Failed to apply patch to {target_path}: {e}")
            return 0

class PromptDistiller:
    """Handles granular distillation of agent instructions in Markdown files."""
    
    @staticmethod
    def apply_distillation(target_path: str, anchor: str, new_text: str) -> int:
        """
        Replaces ALL occurrences of old high-entropy text with new distilled logic.
        Returns the number of replacements made.
        """
        if not anchor or not os.path.exists(target_path):
            return 0

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Strategy: Collapse all anchor whitespace into a flexible pattern
            # 1. Clean the anchor of redundant whitespace
            clean_anchor = re.sub(r'[\s\n\r\t]+', ' ', anchor).strip()
            # 2. Escape regex characters (note: re.escape behavior depends on Python version)
            pattern = re.escape(clean_anchor)
            # 3. Restore flexibility for whitespace: Replace literal spaces OR escaped spaces (\ ) 
            # with a greedy whitespace matcher [\s\r\n\t]+
            pattern = pattern.replace(r'\ ', r'[\s\r\n\t]+').replace(' ', r'[\s\r\n\t]+')
            
            # Count matches before substitution
            matches = len(re.findall(pattern, content))
            if matches > 0:
                new_content = re.sub(pattern, new_text, content, count=0)
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return matches
                
            return 0
            
        except Exception as e:
            logger.error(f"PromptDistiller: Failed to distill {target_path}: {e}")
            return 0
