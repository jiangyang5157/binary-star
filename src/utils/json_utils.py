import json
import os
import numpy as np
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict

from src.utils.logger_utils import setup_logger
logger = setup_logger(__name__)

class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle specialized types:
    - NumPy floats and ints
    - NumPy arrays (converted to lists)
    - Datetime objects (ISO-8601 format)
    - Enums (serialized by name)
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.name
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def convert_to_json_string(data: Any, indent_level: int = 2) -> str:
    """
    Serializes a Python object to a pretty-printed JSON string.
    Uses the EnhancedJSONEncoder for maximum type safety.
    """
    return json.dumps(
        data, 
        cls=EnhancedJSONEncoder, 
        indent=indent_level, 
        ensure_ascii=False
    )

def save_to_json_file(data: Any, file_path: str, indent_level: int = 2) -> bool:
    """
    Saves a Python object to a file in JSON format, creating parent directories if needed.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        json_output = convert_to_json_string(data, indent_level=indent_level)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_output)
        logger.info(f"saved | file={file_path}")
        return True
    except Exception as e:
        logger.error(f"save failed | file={file_path} | error={e}")
        return False

def load_from_json_file(file_path: str) -> Any:
    """
    Loads data from a JSON file. Returns None if the file is missing or corrupted.
    """
    if not os.path.exists(file_path):
        logger.warning(f"not found | file={file_path}")
        return None
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"load failed | file={file_path} | error={e}")
        return None

def _coerce_to_dict(obj: Any) -> Optional[Dict[str, Any]]:
    """Normalise a parsed JSON value to a dict, unwrapping single-element lists."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        if len(obj) == 1 and isinstance(obj[0], dict):
            logger.debug("unwrapped single-element JSON array")
            return obj[0]
        logger.warning(
            "expected JSON object but got list | elements=%d",
            len(obj),
        )
        return None
    logger.warning(
        "expected JSON object but got %s",
        type(obj).__name__,
    )
    return None


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts and parses a JSON object from a string, even if it contains
    conversational filler or trailing garbage characters (e.g. extra braces).
    Uses JSONDecoder().raw_decode to find the logical end of the JSON structure.
    """
    if not text:
        return None

    text = text.strip()

    # 1. Quick try: standard parse
    try:
        return _coerce_to_dict(json.loads(text))
    except Exception:
        pass

    # 2. Advanced try: Find first '{' and use raw_decode
    try:
        start_idx = text.find('{')
        if start_idx != -1:
            json_text = text[start_idx:]
            decoder = json.JSONDecoder()
            # raw_decode returns the object and the byte index where it stopped
            obj, index = decoder.raw_decode(json_text)
            return _coerce_to_dict(obj)
    except Exception as e:
        logger.debug(f"raw_decode failed | error={e}")

    # 3. Fallback: Cleanup common LLM artifacts (markdown blocks)
    try:
        cleaned = text.replace('```json', '').replace('```', '').strip()
        # Find first '{' and last '}'
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1:
            return _coerce_to_dict(json.loads(cleaned[start:end+1]))
    except Exception:
        pass

    return None

# Aliases for backward compatibility
to_json = convert_to_json_string
save_json = save_to_json_file
load_json = load_from_json_file
