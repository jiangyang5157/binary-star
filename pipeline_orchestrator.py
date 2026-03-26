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
        paths = [
            os.path.join(os.getcwd(), "venv", "bin", "python"),
            os.path.join(os.getcwd(), ".venv", "bin", "python"),
            sys.executable
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return sys.executable

    def run_script(self, script_path: str, args: Optional[List[str]] = None) -> bool:
        """Executes a python script as a subprocess."""
        if not os.path.exists(script_path):
            self.logger.error(f"Script not found: {script_path}")
            return False

        full_command = [self.venv_python, script_path] + (args or [])
        display_name = os.path.basename(script_path)
        
        self.logger.info(f">>> Launching: {display_name} {' '.join(args or [])}")
        
        try:
            result = subprocess.run(
                full_command, 
                capture_output=True, 
                text=True, 
                timeout=3600
            )
            
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        self.logger.info(f"[{display_name}] {line}")
            
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

class SequentialPipelineJob(Job):
    """
    A job that runs a sequence of steps (Strategist -> Reviewer).
    """
    def __init__(self, symbol: str, data_root: str, executor: ProcessExecutor):
        self.name = f"Pipeline-{symbol}"
        self.symbol = symbol
        self.data_root = data_root
        self.executor = executor

    def run(self) -> None:
        """Executes the full pipeline cycle for a symbol."""
        # Step 1: Execute Strategist
        strat_args = ["--symbol", self.symbol, "--data_root", self.data_root]
        strat_success = self.executor.run_script("strategist.py", strat_args)
        
        # Step 2: Trigger Reviewer (Checks for any pending reviews)
        # We always trigger the reviewer after a strategy run
        rev_args = ["--data_root", self.data_root]
        self.executor.run_script("reviewer.py", rev_args)

# --- 3. Validation & Management ---

class ConfigValidator:
    """Validates the orchestrator settings against the global agent config."""
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def validate_interval(self, interval_hours: float) -> bool:
        """Ensures the requested interval is greater than the micro analysis timeframe."""
        try:
            from src.utils.agent_utils import load_config
            config = load_config()
            
            micro_interval_str = config['observer']['micro_analysis_context']['time_interval']
            micro_hours = self._parse_time_to_hours(micro_interval_str)
            
            if interval_hours <= micro_hours:
                self.logger.error(
                    f"Invalid Interval: Requested {interval_hours}h is not greater than "
                    f"micro timeframe {micro_interval_str} ({micro_hours}h)."
                )
                return False
            
            self.logger.info(f"Interval validated: {interval_hours}h > {micro_interval_str}")
            return True
        except Exception as e:
            self.logger.warning(f"Could not perform interval validation: {e}. Proceeding anyway.")
            return True

    def _parse_time_to_hours(self, time_str: str) -> float:
        """Parses strings like '15m', '1h', '1d' into float hours."""
        unit = time_str[-1].lower()
        val = float(time_str[:-1])
        mapping = {"m": 1/60, "h": 1, "d": 24}
        return val * mapping.get(unit, 1)

class JobScheduler:
    """Manages the scheduling logic."""
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.schedule = schedule

    def add_job(self, job: Job, interval_hours: float):
        self.logger.info(f"Scheduling '{job.name}' every {interval_hours} hours.")
        self.schedule.every(interval_hours).hours.do(job.run)

    def run_pending(self):
        self.schedule.run_pending()

# --- 4. Orchestrator Service ---

class PipelineOrchestrator:
    def __init__(self, symbol: str, interval: float, data_root: str):
        self.logger = setup_orchestrator_logger()
        self.executor = ProcessExecutor(self.logger)
        self.scheduler = JobScheduler(self.logger)
        self.validator = ConfigValidator(self.logger)
        
        self.symbol = symbol
        self.interval = interval
        self.data_root = data_root

    def start(self):
        """Starts the service cycle."""
        self.logger.info(f"=== Starting Pipeline Orchestrator for {self.symbol} ===")
        
        if not self.validator.validate_interval(self.interval):
            self.logger.error("Validation failed. Aborting startup.")
            sys.exit(1)

        pipeline_job = SequentialPipelineJob(self.symbol, self.data_root, self.executor)

        # Initial run
        self.logger.info("Executing initial startup run...")
        pipeline_job.run()

        # Schedule
        self.scheduler.add_job(pipeline_job, self.interval)

        self.logger.info("Orchestrator monitoring loop active.")
        try:
            while True:
                self.scheduler.run_pending()
                time.sleep(10) # 10s check interval for loop efficiency
        except KeyboardInterrupt:
            self.logger.info("Orchestrator received shutdown signal.")

def main():
    parser = argparse.ArgumentParser(description="SOLID Pipeline Orchestrator")
    parser.add_argument("--symbol", type=str, help="Symbol to oversee (e.g. BTCUSDT)")
    parser.add_argument("--data_root", type=str, required=True, help="Data directory root")
    parser.add_argument("--interval", type=float, required=True, help="Pipeline interval in hours")
    args = parser.parse_args()
    
    # Load global defaults for missing CLI args
    from src.utils.agent_utils import load_global_config
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    if not symbol:
        print("Error: Symbol not provided and no default found in global_config.yaml")
        sys.exit(1)
        
    orchestrator = PipelineOrchestrator(
        symbol=symbol, 
        interval=args.interval, 
        data_root=args.data_root
    )
    orchestrator.start()

if __name__ == "__main__":
    main()
