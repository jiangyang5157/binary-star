import os

def find_project_root() -> str:
    """
    Dynamically finds the project root by searching for config/config.yaml.
    Starts from the current file's directory and walks up.
    """
    current_path = os.path.abspath(os.path.dirname(__file__))
    while current_path != os.path.dirname(current_path): # Stop at filesystem root
        if os.path.exists(os.path.join(current_path, "config", "config.yaml")):
            return current_path
        current_path = os.path.dirname(current_path)
    
    # Fallback to current working directory if not found
    return os.getcwd()
