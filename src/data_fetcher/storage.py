import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class DataStorage:
    @staticmethod
    def save_json(data: Any, filepath: str) -> bool:
        """
        Saves data as a JSON file, creating parent directories if they don't exist.
        """
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            logger.info(f"Successfully saved data to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to save {filepath}: {e}")
            return False
            
    @staticmethod
    def load_json(filepath: str) -> Any:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
            return None
