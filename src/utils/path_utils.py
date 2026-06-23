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


def setup_project_path() -> str:
    """Ensure the project root is on sys.path (for standalone run_*.py scripts).

    Uses resolve_project_root() to find the root via marker files (.git, src/,
    config/strategy_config.yaml) and prepends it to sys.path if not already there.

    Returns the project root path.
    """
    import sys
    root = resolve_project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    return root
