import json
import numpy as np
from datetime import datetime
from enum import Enum
from typing import Any, Optional

class EnhancedJSONEncoder(json.JSONEncoder):
    """
    A custom JSON encoder that handles NumPy types, datetime objects, and Enums.
    Crucial for crypto trading data where these types are frequent.
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

def to_json(data: Any, indent: int = 2) -> str:
    """
    Converts a Python object (usually a dict) into a pretty-printed JSON string.
    Uses the EnhancedJSONEncoder for maximum type safety.
    """
    return json.dumps(data, cls=EnhancedJSONEncoder, indent=indent, ensure_ascii=False)

def save_json(data: Any, file_path: str, indent: int = 2):
    """
    Saves a Python object to a file as JSON.
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(to_json(data, indent=indent))
