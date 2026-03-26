import os
import yaml
import re
from typing import Dict, Any, List


def load_config(config_filepath: str = "config/agent_config.yaml") -> Dict[str, Any]:
    """
    Loads a YAML configuration file from the given path.
    If the path is relative, it is resolved against the project root.
    """
    from src.utils.path_utils import resolve_project_root
    project_root = resolve_project_root()
    
    absolute_path = config_filepath
    if not os.path.isabs(config_filepath):
        absolute_path = os.path.join(project_root, config_filepath)
        
    with open(absolute_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_global_config(config_filepath: str = "config/global_config.yaml") -> Dict[str, Any]:
    """
    Loads the global system configuration file.
    """
    from src.utils.path_utils import resolve_project_root
    project_root = resolve_project_root()
    
    absolute_path = config_filepath
    if not os.path.isabs(config_filepath):
        absolute_path = os.path.join(project_root, config_filepath)
        
    try:
        with open(absolute_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

from functools import lru_cache

@lru_cache(maxsize=32)
def read_prompt_template(prompt_path: str) -> str:
    """
    Reads a prompt template file and returns its content as a string.
    Cached to minimize IO during multi-agent sessions.
    """
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def apply_prompt_logic_filters(template: str, active_passes: List[str]) -> str:
    """
    Filters a prompt template based on active 'PASS' blocks.
    
    Logic:
    1. Supports multiple active passes simultaneously.
    2. Handles nested [[[PASS: name]]] blocks correctly.
    3. Rule: Content is included ONLY if it is NOT inside any INACTIVE pass block.
    """
    # Pattern to match both opening [[[PASS: name]]] and closing [[[/PASS: name]]] tags
    tag_pattern = re.compile(r"(\[\[\[PASS: (.*?)\]\]\]|\[\[\[/PASS: (.*?)\]\]\])")
    
    processed_parts = []
    current_index = 0
    inactive_block_stack = set()
    
    for match in tag_pattern.finditer(template):
        # 1. Capture text before the tag if we are NOT inside an inactive block
        if not inactive_block_stack:
            processed_parts.append(template[current_index:match.start()])
            
        opening_tag_name = match.group(2)
        closing_tag_name = match.group(3)
        
        if opening_tag_name:
            # Entering a new pass block
            pass_id = opening_tag_name.strip()
            if pass_id not in active_passes:
                inactive_block_stack.add(pass_id)
        elif closing_tag_name:
            # Exiting a pass block
            pass_id = closing_tag_name.strip()
            if pass_id in inactive_block_stack:
                inactive_block_stack.remove(pass_id)
                
        current_index = match.end()
        
    # Append the remaining part of the template if it's not excluded
    if not inactive_block_stack:
        processed_parts.append(template[current_index:])
        
    final_output = "".join(processed_parts)
    
    # Cleanup: Collapse 3+ newlines into 2 to prevent excessive whitespace
    final_output = re.sub(r"\n{3,}", "\n\n", final_output)
    
    return final_output.strip()


import string

class SafeFormatter(string.Formatter):
    """
    A custom formatter that returns the key itself (surrounded by braces) 
    if the key is missing from the format arguments.
    """
    def get_value(self, key: Any, args: Any, kwargs: Any) -> Any:
        try:
            return super().get_value(key, args, kwargs)
        except (KeyError, IndexError):
            return f"{{{key}}}"

def safe_format(template: str, **kwargs) -> str:
    """
    Formats a string template using kwargs. 
    Ignores missing keys by keeping them as-is (e.g., '{missing}' stays '{missing}').
    """
    return SafeFormatter().format(template, **kwargs)

