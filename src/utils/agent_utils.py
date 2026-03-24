import os
import yaml
import logging
import re
from typing import Dict, Any, List, Set

def load_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """
    Loads YAML configuration. If config_path is relative, it resolves
    it relative to the project root.
    """
    from src.utils.path_utils import find_project_root
    project_root = find_project_root()
    
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_prompt(prompt_path: str) -> str:
    """Reads a prompt template from disk."""
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def partition_prompt(template: str, active_passes: List[str]) -> str:
    """
    Advanced Prompt Partitioning (The 'Sieve' Algorithm):
    1. Supports multiple active passes simultaneously.
    2. Handles nested [[[PASS]]] blocks correctly.
    3. Rule: Content is included ONLY if it is NOT inside any INACTIVE pass block.
    """
    # Regex to find any start or end tag
    tag_pattern = re.compile(r"(\[\[\[PASS: (.*?)\]\]\]|\[\[\[/PASS: (.*?)\]\]\])")
    
    result_parts = []
    last_pos = 0
    inactive_stack = set()
    
    for match in tag_pattern.finditer(template):
        # 1. Append text before the tag if we are in an active context
        if not inactive_stack:
            result_parts.append(template[last_pos:match.start()])
            
        full_tag = match.group(1)
        start_name = match.group(2)
        end_name = match.group(3)
        
        if start_name:
            # Entering a pass
            if start_name.strip() not in active_passes:
                inactive_stack.add(start_name.strip())
        elif end_name:
            # Exiting a pass
            if end_name.strip() in inactive_stack:
                inactive_stack.remove(end_name.strip())
                
        last_pos = match.end()
        
    # Append remaining text if active
    if not inactive_stack:
        result_parts.append(template[last_pos:])
        
    result = "".join(result_parts)
    
    # Cleanup excessive newlines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()

