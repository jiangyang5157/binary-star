import os
import argparse
import json
import logging
from dotenv import load_dotenv

from src.agent.strategist_agent import StrategistAgent
from src.agent.critic_agent import CriticAgent
from src.utils.agent_utils import load_config
from src.utils.logger_utils import setup_logger
from src.utils.datetime_utils import get_utc_now, FILE_TIMESTAMP_FORMAT, sanitize_timestamp

# Setup logging
logger = setup_logger("StrategistPipeline")


def main():
    parser = argparse.ArgumentParser(description="Strategist Agent Pipeline - Generate trading plans from observations.")
    parser.add_argument("--file", type=str, required=True, help="Path to observation JSON file.")
    parser.add_argument("--data_dir", type=str, help="Override base data directory")
    args = parser.parse_args()
    
    # Load environment variables (API Keys)
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        return
    
    # 1. Load Observation
    if not os.path.exists(args.file):
        logger.error(f"Observation file not found: {args.file}")
        return

    with open(args.file, 'r', encoding='utf-8') as f:
        observation = json.load(f)

    logger.info(f"--- Strategist session START: {observation.get('symbol')} ---")

    config = load_config()
    paths_config = config['paths']
    data_dir = args.data_dir or paths_config['data_dir']

    try:
        # 2. Initialize Agents
        strategist = StrategistAgent(config, api_key=api_key)
        critic = CriticAgent(config, api_key=api_key)

        # 3. Step 1: Drafting (Pass 1)
        logger.info("Step 1: Strategist is drafting initial plan...")
        draft_plan = strategist.draft(observation)
        
        # 4. Step 2: Auditing (Pass 2)
        logger.info("Step 2: Critic is performing adversarial audit...")
        critique = critic.audit(observation, draft_plan)
        
        # 5. Step 3: Synthesis (Pass 3)
        logger.info("Step 3: Strategist is performing final synthesis...")
        final_decision = strategist.synthesize(observation, draft_plan, critique)

        # 6. Save Result (Self-Contained)
        strategies_dir = os.path.join(data_dir, paths_config['strategies_dir'])
        os.makedirs(strategies_dir, exist_ok=True)
        observation_symbol = observation.get('symbol')
        observation_timestamp = observation.get('timestamp')

        # Clean timestamp for filename via standard utility
        timestamp_clean = sanitize_timestamp(observation_timestamp or "")
        
        output_file = os.path.join(strategies_dir, f"{observation_symbol}_strategy_{timestamp_clean}.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "observation": observation,
                "draft": draft_plan,
                "critique": critique,
                "final_decision": final_decision
            }, f, indent=2, ensure_ascii=False)

        logger.info(f"Strategist session COMPLETE. Result saved to: {output_file}")

    except Exception as e:
        logger.error(f"Strategist session FAILED: {e}", exc_info=True)

if __name__ == "__main__":
    main()
