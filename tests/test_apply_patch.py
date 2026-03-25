import unittest
import os
import json
import yaml
import tempfile
import shutil
from apply_patch import PromptEvolutionStrategy, ConfigEvolutionStrategy, setup_evolution_logger

class TestEvolutionStrategies(unittest.TestCase):
    def setUp(self):
        self.logger = setup_evolution_logger()
        self.prompt_strategy = PromptEvolutionStrategy(self.logger)
        self.config_strategy = ConfigEvolutionStrategy(self.logger)
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_prompt_patch_exact_match(self):
        # Setup
        prompt_path = os.path.join(self.test_dir, "test_prompt.md")
        original_content = "Rule 1: Buy low.\nRule 2: Sell high."
        with open(prompt_path, 'w') as f:
            f.write(original_content)

        patches = [
            {"action": "REPLACE", "target": "Buy low.", "replacement": "Buy lower!"},
            {"action": "REMOVE", "target": "Rule 2: Sell high.", "replacement": ""}
        ]

        # Execute
        self.prompt_strategy.apply(prompt_path, patches)

        # Verify
        with open(prompt_path, 'r') as f:
            updated_content = f.read()
        self.assertEqual(updated_content.strip(), "Rule 1: Buy lower!")

    def test_prompt_patch_flexible_whitespace_recovery(self):
        # Setup (Notice the extra spaces/newlines)
        prompt_path = os.path.join(self.test_dir, "test_flex.md")
        original_content = "Rule 1: **LONG   LOGIC**\n\nTarget is here."
        with open(prompt_path, 'w') as f:
            f.write(original_content)

        # Target has normalized single spaces, but source has 3 spaces
        patches = [
            {"action": "REPLACE", "target": "Rule 1: **LONG LOGIC**", "replacement": "Evolved Logic!"}
        ]

        # Execute
        self.prompt_strategy.apply(prompt_path, patches)

        # Verify
        with open(prompt_path, 'r') as f:
            updated_content = f.read()
        # Flexible matching (Recovery) should succeed
        self.assertIn("Evolved Logic!", updated_content)

    def test_prompt_add_to_section(self):
        # Setup
        prompt_path = os.path.join(self.test_dir, "test_add.md")
        original_content = "# PROTOCOLS\n1. Rule A\n\n# CONFIG\n2. Rule B"
        with open(prompt_path, 'w') as f:
            f.write(original_content)

        patches = [
            {"action": "ADD", "target": "PROTOCOLS", "replacement": "3. New Rule X"}
        ]

        # Execute
        self.prompt_strategy.apply(prompt_path, patches)

        # Verify
        with open(prompt_path, 'r') as f:
            updated_content = f.read()
        # Should be inserted after the PROTOCOLS header
        self.assertIn("# PROTOCOLS\n3. New Rule X", updated_content)

    def test_config_patch_merge(self):
        # Setup
        config_path = os.path.join(self.test_dir, "test_config.yaml")
        original_config = {
            "observer": {"threshold": 0.5, "lookback": 5},
            "strategist": {"risk": "low"}
        }
        with open(config_path, 'w') as f:
            yaml.dump(original_config, f)

        updates = {
            "observer": {"lookback": 10, "new_param": True},
            "critic": {"strict_mode": True}
        }

        # Execute
        self.config_strategy.apply(config_path, updates)

        # Verify
        with open(config_path, 'r') as f:
            updated_config = yaml.safe_load(f)
        
        self.assertEqual(updated_config["observer"]["lookback"], 10)
        self.assertTrue(updated_config["observer"]["new_param"])
        self.assertEqual(updated_config["observer"]["threshold"], 0.5)
        self.assertTrue(updated_config["critic"]["strict_mode"])

if __name__ == '__main__':
    unittest.main()
