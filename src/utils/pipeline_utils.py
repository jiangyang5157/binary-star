import os
import yaml
import re
import argparse
import hashlib
from typing import Dict, Any, List, Optional

def get_file_hash(file_path: str) -> str:
    """Calculates a short MD5 hash of a file's content to track prompt/config versions."""
    try:
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return "unavailable"
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except Exception:
        return "unavailable"


def load_config(config_filepath: str = "config/strategy_config.yaml") -> Dict[str, Any]:
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


def load_combined_config(global_path: str = "config/global_config.yaml", strategy_path: str = "config/strategy_config.yaml") -> Dict[str, Any]:
    """
    Loads and merges global and strategy configurations.
    Priority: Strategy config values override Global config values if there's a conflict
    at the top level, but typically they have distinct top-level keys.
    """
    global_cfg = load_global_config(global_path)
    strategy_cfg = load_config(strategy_path)
    # Shallow merge of top-level keys (system, network, analysis_window, etc.)
    return {**global_cfg, **strategy_cfg}

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

def resolve_data_root(data_root_arg: Optional[str]) -> str:
    """
    Resolves a data root path, checking against predefined mappings in global_config.
    Example: 'once' -> 'data/once'
    """
    if not data_root_arg:
        return ""
        
    global_cfg = load_global_config()
    mapping = global_cfg.get('system', {}).get('data_root_mapping', {})
    
    # Return mapped value if exists, otherwise return original
    return mapping.get(data_root_arg, data_root_arg)


# --- STRATEGIC ARCHIVAL & PERSISTENCE ---

def add_data_root_argument(parser: argparse.ArgumentParser):
    """
    Standardizes the addition of data_root and env shortcut arguments.
    """
    parser.add_argument(
        "--env", 
        dest="env_shortcut",
        default="once",
        help="Environment shortcut (e.g., once, live, test). Maps to --data_root if provided."
    )
    parser.add_argument(
        "--data_root", 
        type=str, 
        required=False, 
        help="Explicit data directory root. Overrides env_shortcut."
    )


def archive_strategy_result(symbol: str, timestamp, result: Any, data_root: str, target_dir: str) -> str:
    """
    Standardized archival for all pipeline results.
    Moved from legacy strategist.py to core utilities.
    """
    from src.utils.path_utils import resolve_project_root
    from src.utils.datetime_utils import sanitize_timestamp
    from src.utils.json_utils import save_json
    
    project_root = resolve_project_root()
    output_dir = os.path.join(project_root, data_root, target_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    ts_str = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
    ts_suffix = sanitize_timestamp(ts_str)
    
    # v5.10 PHYSICAL HARDENING: Final micro-alignment of professional prefixes
    prefix_map = {"sessions": "session", "audits": "audit", "market": "market"}
    file_prefix = prefix_map.get(target_dir, target_dir)
    
    filename = f"{symbol}_{file_prefix}_{ts_suffix}.json"
    output_file = os.path.join(output_dir, filename)
    
    save_json(result, output_file)
    return output_file

