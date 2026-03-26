import os
import json
import yaml
import re
import argparse
import logging
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

# --- CORE LOGGING SETUP ---
def setup_evolution_logger() -> logging.Logger:
    """Configures a standardized logger for systemic evolution events."""
    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger("EvolutionEngine")

# --- STRATEGY INTERFACE ---
class EvolutionStrategy(ABC):
    """
    Abstract Base Class for all evolution sub-strategies.
    Following the Strategy Pattern to keep the core Engine open for extension.
    """
    @abstractmethod
    def apply(self, target_path: str, payload: Any):
        """Applies a specific change payload to a target file."""
        pass

# --- CONCRETE STRATEGIES ---
class PromptEvolutionStrategy(EvolutionStrategy):
    """
    Handles granular prompt updates in Markdown files.
    Features 'Industrial-Grade' regex flexible matching for robust patch application.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def apply(self, target_path: str, patches: List[Dict[str, str]]):
        if not patches or not os.path.exists(target_path):
            return

        self.logger.info(f"Evolving Prompt Logics: {target_path} ({len(patches)} patches)")
        
        with open(target_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        
        for patch in patches:
            action = patch.get("action", "").upper()
            target = patch.get("target", "")
            replacement = patch.get("replacement", "")

            if action == "ADD":
                content = self._handle_add(content, target, replacement, target_path)
            elif action in ["REPLACE", "REMOVE"]:
                content = self._handle_transformation(content, action, target, replacement, target_path)

        if content != original_content:
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.info(f"  [SUCCESS] Updated {target_path}")

    def _handle_add(self, content: str, section: str, logic: str, path: str) -> str:
        """Finds a section header (or bolded title) and inserts the new logic directly beneath it."""
        # Match lines starting with # (Markdown header) OR ** (Bolded section title)
        header_pattern = rf"^((?:#+|\*\*).*{re.escape(section)}.*)$"
        match = re.search(header_pattern, content, re.MULTILINE)
        
        if match:
            header_pos = match.end()
            self.logger.info(f"  [ADD] Inserted logic into section '{section}'")
            return content[:header_pos] + f"\n{logic}" + content[header_pos:]
        
        self.logger.warning(f"  [ADD_FALLBACK] Section '{section}' not found in {path}. Appending to EOF.")
        return content + f"\n\n{logic}\n"

    def _handle_transformation(self, content: str, action: str, target: str, replacement: str, path: str) -> str:
        """Applies REPLACE or REMOVE with a two-stage matching strategy (Exact -> Regex)."""
        new_val = replacement if action == "REPLACE" else ""
        
        # 1. Exact Match (High Precision)
        if target in content:
            self.logger.info(f"  [{action}] Exact match succeeded.")
            return content.replace(target, new_val)
        
        # 2. Flexible Whitespace Match (Recovery Strategy)
        escaped_target = re.escape(target)
        flexible_pattern = re.sub(r'\\\s+', r'\\s+', escaped_target)
        
        if re.search(flexible_pattern, content):
            self.logger.info(f"  [{action}_RECOVERY] Flexible whitespace match succeeded for '{target[:30]}...'")
            return re.sub(flexible_pattern, new_val, content, count=1)
        
        self.logger.error(f"  [FAILED] Target completely missing from {path}: '{target[:50]}...'")
        return content

class ConfigEvolutionStrategy(EvolutionStrategy):
    """
    Handles systemic configuration updates in YAML files.
    Supports deep merging of parameters for nested component configs.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def apply(self, target_path: str, updates: Dict[str, Dict[str, Any]]):
        if not updates or not any(updates.values()) or not os.path.exists(target_path):
            return

        self.logger.info(f"Evolving System Parameters: {target_path}")
        
        with open(target_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        modified = False
        for component, params in updates.items():
            if isinstance(params, dict) and params:
                if component not in config:
                    config[component] = {}
                config[component].update(params)
                modified = True
                self.logger.info(f"  [CONFIG] Updated '{component}' parameters.")

        if modified:
            with open(target_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, sort_keys=False, default_flow_style=False)
            self.logger.info(f"  [SUCCESS] Updated {target_path}")

# --- SYSTEM ORCHESTRATOR (THE ENGINE) ---
class SystemEvolutionEngine:
    """
    Industrial-Grade Orchestrator for systemic evolution.
    Coordinates multiple strategies to evolve the entire trading ecosystem.
    """
    def __init__(self):
        self.logger = setup_evolution_logger()
        self.prompt_worker = PromptEvolutionStrategy(self.logger)
        self.config_worker = ConfigEvolutionStrategy(self.logger)

    def evolve(self, coach_report_path: str):
        """Loads a Coach JSON report and dispatches evolution tasks."""
        if not os.path.exists(coach_report_path):
            self.logger.error(f"Evolution report not found: {coach_report_path}")
            return

        self.logger.info(f"=== Starting Systemic Evolution for {os.path.basename(coach_report_path)} ===")

        try:
            with open(coach_report_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
            
            # The report structure often nests the analysis under 'strategic_analysis'
            analysis = report.get("strategic_analysis", report)
            
            # 1. Evolve Domain Agents (Prompts)
            self.prompt_worker.apply(
                "src/agent/prompts/strategist.md", 
                analysis.get("strategist_prompt_patches", [])
            )
            self.prompt_worker.apply(
                "src/agent/prompts/critic.md", 
                analysis.get("critic_prompt_patches", [])
            )

            # 2. Evolve System Parameters (Config)
            self.config_worker.apply(
                "config/agent_config.yaml",
                analysis.get("config_updates", {})
            )
            
            self.logger.info("=== Evolution Cycle Completed ===")

        except Exception as e:
            self.logger.error(f"Critical failure during evolution cycle: {e}")

# --- CLI INTERFACE ---
def main():
    parser = argparse.ArgumentParser(
        description="Industrial-Grade Automated System Evolution Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Usage: python3 apply_patch.py --file data/test/coaches/report.json"
    )
    parser.add_argument(
        "--file", 
        type=str, 
        required=True, 
        help="Path to the Strategist/Coach JSON report containing evolution logic."
    )
    args = parser.parse_args()

    engine = SystemEvolutionEngine()
    engine.evolve(args.file)

if __name__ == "__main__":
    main()
