import os

def resolve_project_root() -> str:
    """
    Dynamically finds the project root by searching for common markers:
    - .git directory
    - src directory
    - config/strategy_config.yaml
    
    Starts from the current file's directory and traverses upward.
    """
    search_path = os.path.abspath(os.path.dirname(__file__))
    
    while search_path != os.path.dirname(search_path):  # Stop at filesystem root
        markers = [
            os.path.join(search_path, ".git"),
            os.path.join(search_path, "src"),
            os.path.join(search_path, "config", "strategy_config.yaml")
        ]
        
        if any(os.path.exists(marker) for marker in markers):
            return search_path
            
        search_path = os.path.dirname(search_path)
    
    # Fallback to current working directory if no markers are found
    return os.getcwd()
# Alias for backward compatibility
find_project_root = resolve_project_root
