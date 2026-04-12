import os
import re
import logging
import collections.abc
from typing import Dict, Any, List
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
                
                # A. Detect ground-truth indentation context
                lines_before = content[:match_start].split('\n')
                # Since the new pattern captures the leading whitespace, 
                # the match_start is now the TRUE start of the line (or starts with \n).
                # We look at the line ABOVE the match to find the list's baseline.
                list_baseline_indent = ""
                for prev_line in reversed(lines_before):
                    stripped_prev = prev_line.strip()
                    if stripped_prev:
                        if stripped_prev.startswith('-'):
                            m = re.match(r'^\s*', prev_line)
                            list_baseline_indent = m.group(0) if m else ""
                            break
                        # Stop if we hit a different structure
                        break

                ambient_prefix = list_baseline_indent
                
                # B. Forceful Re-alignment to the list baseline
                patch_lines = new_text.split('\n')
                final_output_lines = []
                
                non_empty_patch_lines = [l for l in patch_lines if l.strip()]
                if not non_empty_patch_lines:
                    return new_text
                
                def get_indent_len(l):
                    m = re.match(r'^\s*', l)
                    return len(m.group(0)) if m else 0
                
                min_patch_indent_len = min(get_indent_len(l) for l in non_empty_patch_lines)
                
                for line in patch_lines:
                    stripped = line.lstrip()
                    if not stripped:
                        final_output_lines.append("")
                        continue
                    
                    rel_nesting = get_indent_len(line) - min_patch_indent_len
                    final_output_lines.append(f"{ambient_prefix}{' ' * rel_nesting}{stripped}")
                
                return '\n'.join(final_output_lines)

            # Build a pattern that captures the optional leading whitespace of the line
            clean_anchor = re.sub(r'[\s\n\r\t]+', ' ', anchor).strip()
            # The pattern now swallows any leading whitespace on the same line to prevent stacking
            pattern = r'^[ \t]*' + re.escape(clean_anchor).replace(r'\ ', r'[\s\r\n\t]+').replace(' ', r'[\s\r\n\t]+')
            
            # Count matches using MULTILINE to make ^ work for each line
            matches = len(re.findall(pattern, content, flags=re.MULTILINE))
            if matches > 0:
                # Apply replacement with MULTILINE
                return re.sub(pattern, align_and_replace, content, count=0, flags=re.MULTILINE)
            
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
