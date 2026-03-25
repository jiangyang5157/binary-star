import json
import os
import logging
import numpy as np
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

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
        logger.info(f"Successfully saved data to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON to {file_path}: {e}")
        return False

def load_from_json_file(file_path: str) -> Any:
    """
    Loads data from a JSON file. Returns None if the file is missing or corrupted.
    """
    if not os.path.exists(file_path):
        logger.warning(f"JSON file not found: {file_path}")
        return None
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON from {file_path}: {e}")
        return None
