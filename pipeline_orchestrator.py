#!/usr/bin/env python3
import os
import sys
import time
import yaml
import logging
import argparse
import subprocess
import schedule
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# --- 1. Infrastructure: Logging & Execution ---

def setup_orchestrator_logger(name: str = "Orchestrator") -> logging.Logger:
    """Configures a standardized logger for the orchestration service."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # Console Handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        # File Handler
        fh = logging.FileHandler("orchestrator.log")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger

class ProcessExecutor:
    """
    Handles the execution of external processes.
    Enforces isolation and provides structured logging of child process output.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.venv_python = self._resolve_python_path()

    def _resolve_python_path(self) -> str:
        """Determines the path to the virtual environment's python interpreter."""
        # Check for standard venv patterns
        paths = [
            os.path.join(os.getcwd(), "venv", "bin", "python"),
            os.path.join(os.getcwd(), ".venv", "bin", "python"),
            sys.executable # Fallback
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return sys.executable

    def run_script(self, script_path: str, args: Optional[List[str]] = None) -> bool:
        """Executes a python script as a subprocess."""
        full_command = [self.venv_python, script_path] + (args or [])
        display_name = os.path.basename(script_path)
        
        self.logger.info(f">>> Launching: {display_name} {' '.join(args or [])}")
        
        try:
            result = subprocess.run(
                full_command, 
                capture_output=True, 
                text=True, 
                timeout=3600 # 1 hour safety timeout
            )
            
            # Log standard output
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        self.logger.info(f"[{display_name}] {line}")
            
            # Log standard error as warnings
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        self.logger.warning(f"[{display_name} ERR] {line}")

            if result.returncode == 0:
                self.logger.info(f"Successfully completed: {display_name}")
                return True
            else:
                self.logger.error(f"Execution failed: {display_name} (Exit Code: {result.returncode})")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error(f"Execution TIMEOUT: {display_name} exceeded 1 hour.")
            return False
        except Exception as e:
            self.logger.error(f"Execution ERROR: {display_name} - {str(e)}")
            return False

# --- 2. Abstractions: Jobs & Tasks ---

class Job(ABC):
    """Abstract base class for a unit of work that can be scheduled."""
    @abstractmethod
    def run(self) -> None:
        pass

class ScriptJob(Job):
    """A concrete job that executes a Python script."""
    def __init__(self, name: str, script_path: str, executor: ProcessExecutor, args: Optional[List[str]] = None):
        self.name = name
        self.script_path = script_path
        self.executor = executor
        self.args = args or []

    def run(self) -> None:
        self.executor.run_script(self.script_path, self.args)

# --- 3. Management: Configuration & Scheduling ---

class ConfigManager:
    """Handles loading and validation of the orchestrator configuration."""
    def __init__(self, config_path: str, logger: logging.Logger):
        self.config_path = config_path
        self.logger = logger

    def load(self) -> Dict[str, Any]:
        """Loads and validates the YAML configuration."""
        if not os.path.exists(self.config_path):
            self.logger.error(f"Configuration file not found: {self.config_path}")
            raise FileNotFoundError(self.config_path)

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if not config:
                raise ValueError("Empty configuration file.")
        
        # Validate required section
        if 'automation' not in config:
            raise KeyError("Missing 'automation' section in config.")
            
        return config

class JobScheduler:
    """Manages the scheduling of Jobs using the schedule library."""
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.schedule = schedule

    def add_job(self, job: Job, interval_hours: float):
        """Schedules a job to run at a fixed interval."""
        self.logger.info(f"Scheduling job '{getattr(job, 'name', 'Unknown')}' every {interval_hours} hours.")
        # Conversion to minutes/seconds if needed for precise scheduling
        if interval_hours < 0.01: # Use seconds for very short intervals (testing)
            self.schedule.every(int(interval_hours * 3600)).seconds.do(job.run)
        else:
            self.schedule.every(interval_hours).hours.do(job.run)

    def run_pending(self):
        """Executes jobs that are due for execution."""
        self.schedule.run_pending()

# --- 4. Orchestrator Service ---

class PipelineOrchestrator:
    """
    Main service class for managing the automated crypto trading pipeline.
    """
    def __init__(self, config_path: str, is_mock: bool = False):
        self.logger = setup_orchestrator_logger()
        self.executor = ProcessExecutor(self.logger)
        self.scheduler = JobScheduler(self.logger)
        self.config_manager = ConfigManager(config_path, self.logger)
        self.is_mock = is_mock

    def bootstrap(self):
        """Initializes the service, loads config, and registers initial jobs."""
        self.logger.info("=== Bootstrapping Pipeline Orchestrator ===")
        
        config = self.config_manager.load()
        auto_cfg = config['automation']
        
        # Define scripts based on mode
        if self.is_mock:
            strat_script = "mock_strategist.py"
            rev_script = "mock_reviewer.py"
        else:
            strat_script = "strategist.py"
            rev_script = "reviewer.py"

        # Initialize Jobs
        # You can extend this to run different symbols if needed by passing args
        strat_job = ScriptJob("Strategist", strat_script, self.executor, ["--symbol", "BTCUSDT"])
        rev_job = ScriptJob("Reviewer", rev_script, self.executor)

        # Register with Scheduler
        self.scheduler.add_job(strat_job, auto_cfg['prediction_interval_hours'])
        self.scheduler.add_job(rev_job, auto_cfg['review_interval_hours'])

        # Initial Startup Execution
        self.logger.info("Executing initial startup run...")
        strat_job.run()
        rev_job.run()

    def run_forever(self):
        """Main loop: waits and triggers scheduled tasks."""
        self.logger.info("Orchestrator loop started. Monitoring tasks...")
        try:
            while True:
                self.scheduler.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Orchestrator received shutdown signal.")
        except Exception as e:
            self.logger.critical(f"Orchestrator crashed: {e}", exc_info=True)

def main():
    parser = argparse.ArgumentParser(description="Clean Code Pipeline Orchestrator")
    parser.add_argument("--config", type=str, default="config/config.yaml", help="Path to config file")
    parser.add_argument("--mock", action="store_true", help="Run with mock scripts for verification")
    args = parser.parse_args()

    orchestrator = PipelineOrchestrator(args.config, is_mock=args.mock)
    try:
        orchestrator.bootstrap()
        orchestrator.run_forever()
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
