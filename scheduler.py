import schedule
import time
import subprocess
import logging
import yaml
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("automation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def run_script(script_name):
    """
    Helper to run a python script using the venv interpreter.
    """
    logger.info(f">>> Starting execution of {script_name}...")
    venv_python = os.path.join(os.getcwd(), "venv/bin/python")
    
    try:
        result = subprocess.run([venv_python, script_name], capture_output=True, text=True)
        
        # Log stdout if present
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    logger.info(f"[{script_name}] {line}")
        
        # Log stderr if present (usually errors or warnings)
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                if line.strip():
                    logger.warning(f"[{script_name} ERR] {line}")

        if result.returncode == 0:
            logger.info(f"Successfully finished {script_name}")
        else:
            logger.error(f"Error running {script_name} (Exit Code: {result.returncode})")
    except Exception as e:
        logger.error(f"Failed to trigger {script_name}: {e}")

def job_trader():
    run_script("main.py")

def job_reviewer():
    run_script("review.py")

def start_scheduler():
    # Load config to get intervals
    config_path = "config/config.yaml"
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Could not load config: {e}")
        return

    automation = config['automation']
    
    # Pre-flight check for scheduler
    pred_hours = automation['prediction_interval_hours']
    rev_hours = automation['review_interval_hours']

    logger.info("=== Crypto Triple-Agent Scheduler Started ===")
    logger.info(f"Trader Interval: {pred_hours} hours")
    logger.info(f"Reviewer Interval: {rev_hours} hours")

    # Schedule tasks
    schedule.every(pred_hours).hours.do(job_trader)
    schedule.every(rev_hours).hours.do(job_reviewer)

    # Run once immediately on start
    logger.info("Performing initial startup run...")
    job_trader()
    job_reviewer()

    while True:
        schedule.run_pending()
        time.sleep(60) # Only check every minute

if __name__ == "__main__":
    start_scheduler()
