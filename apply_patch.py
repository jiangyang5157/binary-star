import os
import json
import argparse
import logging

def setup_logger():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger("PatchEvolution")

class PatchApplier:
    def __init__(self):
        self.logger = setup_logger()

    def apply_patch(self, report_path: str):
        if not os.path.exists(report_path):
            self.logger.error(f"Coach report file not found: {report_path}")
            return

        self.logger.info(f"Loading coach report: {report_path}")

        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            analysis = data.get("strategic_analysis", {})
            
            # Apply patches to Strategist
            self._patch_file(
                "src/agent/prompts/strategist.md", 
                analysis.get("strategist_prompt_patches", [])
            )
            
            # Apply patches to Critic
            self._patch_file(
                "src/agent/prompts/critic.md", 
                analysis.get("critic_prompt_patches", [])
            )

            # Apply config updates
            self._patch_config(
                "config/agent_config.yaml",
                analysis.get("config_updates", {})
            )
            
        except Exception as e:
            self.logger.error(f"Failed to apply patches from {report_path}: {e}")

    def _patch_config(self, filepath: str, updates: dict):
        if not updates or not any(updates.values()):
            return

        if not os.path.exists(filepath):
            self.logger.warning(f"Config file not found for patching: {filepath}")
            return

        self.logger.info(f"Applying config updates to {filepath}...")
        
        import yaml
        with open(filepath, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        modified = False
        # Universal update: Iterate over any section provided (observer, strategist, critic, reviewer, coach, etc.)
        for section, section_updates in updates.items():
            if isinstance(section_updates, dict) and section_updates:
                if section not in config:
                    config[section] = {}
                config[section].update(section_updates)
                modified = True
                self.logger.info(f"  [CONFIG] Updated '{section}' parameters.")

        if modified:
            with open(filepath, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, sort_keys=False, default_flow_style=False)
            self.logger.info(f"Updated {filepath} successfully.")
        else:
            self.logger.warning(f"No config changes applied.")

    def _patch_file(self, filename: str, patches: list):
        if not patches:
            return

        if not os.path.exists(filename):
            self.logger.warning(f"Target file not found for patching: {filename}")
            return

        self.logger.info(f"Applying {len(patches)} patches to {filename}...")
        
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        import re
        
        for patch in patches:
            action = patch.get("action", "").upper()
            target = patch.get("target", "")
            replacement = patch.get("replacement", "")

            if action == "ADD":
                # ADD: Target the specific section header
                header_pattern = rf"^(#+.*{re.escape(target)}.*)$"
                match = re.search(header_pattern, content, re.MULTILINE)
                
                if match:
                    header_pos = match.end()
                    content = content[:header_pos] + f"\n{replacement}" + content[header_pos:]
                    self.logger.info(f"  [ADD] Inserted new logic into section '{target}'")
                else:
                    # Fallback to appending at the end
                    content += f"\n\n{replacement}\n"
                    self.logger.warning(f"  [ADD] Section '{target}' not found. Appended to EOF.")

            elif action in ["REPLACE", "REMOVE"]:
                # 1. Try Exact Match
                if target in content:
                    content = content.replace(target, replacement if action == "REPLACE" else "")
                    self.logger.info(f"  [REPLACE/REMOVE] Exact match succeeded for target.")
                    continue
                
                # 2. Flexible Whitespace Match (Recovery)
                escaped_target = re.escape(target)
                flexible_pattern = re.sub(r'\\\s+', r'\\s+', escaped_target)
                
                if re.search(flexible_pattern, content):
                    self.logger.info(f"  [RECOVERY] Flexible whitespace match succeeded for target.")
                    content = re.sub(flexible_pattern, replacement if action == "REPLACE" else "", content, count=1)
                else:
                    self.logger.error(f"  [FATAL] Target substring completely missing from {filename}!")
                    self.logger.error(f"  -> Missing Target: {target}")

        if content != original_content:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.info(f"Updated {filename} successfully.")
        else:
            self.logger.warning(f"No changes applied to {filename}.")

def main():
    parser = argparse.ArgumentParser(description="Automated Prompt & Config Evolution Patcher")
    parser.add_argument("--file", type=str, required=True, help="Path to the Coach JSON report file.")
    args = parser.parse_args()

    applier = PatchApplier()
    applier.apply_patch(args.file)

if __name__ == "__main__":
    main()
