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
    def apply_patch(target_config_path: str, key: str, value: Any, target_path: str = "") -> int:
        """
        Applies a parameter overlay with precise path targeting or recursive search.
        Returns the number of keys updated.
        """
        if not key or not os.path.exists(target_config_path):
            return 0

        try:
            yaml = YAML()
            yaml.preserve_quotes = True
            yaml.indent(mapping=2, sequence=4, offset=2)
            
            with open(target_config_path, 'r', encoding='utf-8') as f:
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
            if target_path:
                # 1. Path-specific update (Precise)
                parts = target_path.split('.')
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
                with open(target_config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f)
                
            return update_count
            
        except Exception as e:
            logger.error(f"ConfigPatcher: Failed to apply patch to {target_path}: {e}")
            return 0

class PromptDistiller:
    """Handles granular distillation of agent instructions in Markdown files."""
    
    @staticmethod
    def distill_content(content: str, anchor: str, new_text: str) -> str:
        """
        Pure function: Replaces anchor with new_text in the provided content string.
        Utilizes flexible whitespace matching for robust distillation.
        v6.20: Enhanced with Indentation Awareness to align AI suggestions with target file.
        """
        if not anchor or not content or new_text is None:
            return content

        try:
            # 1. Clean the anchor of redundant whitespace for robust matching
            clean_anchor = re.sub(r'[\s\n\r\t]+', ' ', anchor).strip()
            # 2. Escape regex characters
            pattern = re.escape(clean_anchor)
            # 3. Restore flexibility for whitespace
            pattern = pattern.replace(r'\ ', r'[\s\r\n\t]+').replace(' ', r'[\s\r\n\t]+')
            
            def align_and_replace(match):
                if not new_text:
                    return ""
                    
                match_start = match.start()
                
                # A. Detect ambient indentation in the target file (preceding whitespace on the same line)
                preceding_content = content[:match_start]
                last_newline = preceding_content.rfind('\n')
                ambient_prefix = preceding_content[last_newline + 1:] if last_newline != -1 else preceding_content
                
                # Only apply alignment if the match is at the start of a line (only whitespace precedes it)
                if not ambient_prefix.isspace() and ambient_prefix != "":
                    return new_text

                ambient_indent = ambient_prefix
                
                # B. Detect provided base indentation of the AI's first line of replacement
                lines = new_text.split('\n')
                first_line = lines[0]
                provided_indent_match = re.match(r'^\s*', first_line)
                provided_base = provided_indent_match.group(0) if provided_indent_match else ""
                
                # C. Shift all lines in the replacement block to match ambient indentation
                shifted_lines = []
                for line in lines:
                    if not line.strip():
                        shifted_lines.append("") # Preserve blank lines
                        continue
                    
                    if line.startswith(provided_base):
                        # Swap the AI's guessed indentation with the ground truth from the file
                        shifted_line = ambient_indent + line[len(provided_base):]
                        shifted_lines.append(shifted_line)
                    else:
                        # Fallback for inconsistent indentation within the patch block
                        shifted_lines.append(line)
                
                return '\n'.join(shifted_lines)

            # Count matches first for reporting
            matches = len(re.findall(pattern, content))
            if matches > 0:
                # Use sub with callback to perform context-aware alignment for every instance
                return re.sub(pattern, align_and_replace, content, count=0)
            
            return content
        except Exception as e:
            logger.error(f"PromptDistiller: Internal distillation failure: {e}")
            return content

    @staticmethod
    def apply_distillation(target_path: str, anchor: str, new_text: str) -> int:
        """
        Physical Update: Replaces ALL occurrences of anchor in a file.
        Returns the number of matches replaced.
        """
        if not anchor or not os.path.exists(target_path) or new_text is None:
            return 0

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = PromptDistiller.distill_content(content, anchor, new_text)
            
            if new_content != content:
                # Count matches manually for the return value
                clean_anchor = re.sub(r'[\s\n\r\t]+', ' ', anchor).strip()
                pattern = re.escape(clean_anchor).replace(r'\ ', r'[\s\r\n\t]+').replace(' ', r'[\s\r\n\t]+')
                matches = len(re.findall(pattern, content))

                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return matches
                
            return 0
            
        except Exception as e:
            logger.error(f"PromptDistiller: Failed to distill file {target_path}: {e}")
            return 0

    @staticmethod
    def apply_batch_distillation(content: str, refinements: List[Dict[str, Any]]) -> str:
        """
        Batch Logic: Applies multiple refinements to a single string in-memory.
        Useful for shadow replays in the sandbox.
        """
        if not refinements or not content:
            return content

        patched_content = content
        for p in refinements:
            anchor = p.get('anchor_text')
            new_text = p.get('replaced_with')
            
            if anchor and new_text:
                patched_content = PromptDistiller.distill_content(patched_content, anchor, new_text)
        
        return patched_content
