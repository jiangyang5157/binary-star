#!/usr/bin/env python3
import os
import sys
import argparse
import logging

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.json_utils import load_json
from src.utils.evolution_utils import ConfigPatcher, PromptDistiller
from src.utils.path_utils import resolve_project_root
from src.utils.logger_utils import setup_logger

def main():
    parser = argparse.ArgumentParser(description="Singularity Physical Evolution Synchronizer")
    parser.add_argument("--file", "-f", required=True, help="Path to the validated evolution proposal JSON")
    parser.add_argument("--symbol", type=str, help="Trading symbol for symbol-aware patching")

    args = parser.parse_args()

    # 1. Dynamically resolve project root for testing compatibility
    root = resolve_project_root()

    # 2. Initialize Logging
    setup_logger("PatchRunner")
    logger = logging.getLogger("PatchRunner")

    # 3. Hardcoded Physical Targets
    target_config = "config/strategy_config.yaml"
    config_abs_path = os.path.join(root, target_config)

    # Resolve symbol if provided
    symbol = None
    if args.symbol:
        from src.utils.symbol_utils import resolve_symbol
        symbol = resolve_symbol(args.symbol)

    if not os.path.exists(args.file):
        logger.error(f"Proposal JSON NOT found: {args.file}")
        sys.exit(1)

    proposal = load_json(args.file)
    logger.info(f"Patching: Initiating physical sync from: {os.path.basename(args.file)}...")

    # 3. Synchronize Config Patches
    config_patches = proposal.get('config_patch', [])

    if config_patches:
        logger.info(f"Patching: Applying {len(config_patches)} configuration changes to: {target_config}...")
        for p in config_patches:
            key = p.get('target_key')
            val = p.get('replaced_with')
            t_path = p.get('target_path', "")

            if symbol:
                from src.config.symbol_resolver import patch_config
                updates = patch_config(symbol, t_path, key, val)
                if updates > 0:
                    logger.info(f"Patching:   (+) Updated '{key}' for {symbol} (overrides)")
                else:
                    logger.warning(f"Patching:   (!) FAILED to update '{key}' for {symbol}")
            else:
                updates = ConfigPatcher.apply_patch(config_abs_path, key, val, t_path)
                if updates > 0:
                    logger.info(f"Patching:   (+) Updated '{key}' in {target_config}")
                else:
                    logger.warning(f"Patching:   (!) FAILED to update '{key}' in {target_config}")
                
    # 4. Synchronize Semantic Refinements (Prompt Patches)
    semantic_patches = proposal.get('semantic_refinement', [])
    PROMPT_MAP = {
        "session": "config/prompts/session.md",
        "critic": "config/prompts/critic.md",
        "binary_star": "config/prompts/binary_star.md"
    }
    
    if semantic_patches:
        logger.info(f"Patching: Applying {len(semantic_patches)} semantic refinements...")
        for p in semantic_patches:
            module = p.get('target_module', '').lower()
            anchor = p.get('anchor_text')
            logic = p.get('replaced_with')
            
            rel_path = PROMPT_MAP.get(module)
            if not rel_path:
                logger.error(f"Patching:   (!) Unknown module: {module}. Skipping.")
                continue
                
            abs_path = os.path.join(root, rel_path)
            replacements = PromptDistiller.apply_distillation(abs_path, anchor, logic)
            
            if replacements > 0:
                logger.info(f"Patching:   (+) Replaced {replacements} instances in {rel_path}")
            else:
                logger.warning(f"Patching:   (!) NO MATCH for anchor in {rel_path}. Check target context.")
                
    logger.info("Patching: Physical synchronization COMPLETE.")
    print(f"✅ Physical Sync Successful: {os.path.basename(args.file)} has been moved to production.")

if __name__ == "__main__":
    main()
