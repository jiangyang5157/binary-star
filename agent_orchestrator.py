#!/usr/bin/env python3
import os
import sys
import time
import yaml
import logging
import argparse
import subprocess
import schedule
import pandas as pd
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from src.infrastructure.binance.client import BinanceFuturesClient
from src.analyzer.market_regime import MarketRegimeAnalyzer, MarketRegimeConfig
from src.utils.agent_utils import load_config, resolve_data_root, add_data_root_argument, load_global_config
from src.analyzer.opportunity_scanner import OpportunityScanner
from src.agent.binary_star_orchestrator import BinaryStarOrchestrator
from src.infrastructure.notifications.email_notifier import StrategyNotifier
from src.utils.agent_utils import load_config, archive_strategy_result

# Setup paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.logger_utils import setup_logger

# --- 1. Infrastructure: Logging & Execution ---

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

    def run_script(self, script_path: str, args: List[str]) -> bool:
        """Executes a python script as a separate process."""
        if not os.path.exists(script_path):
            self.logger.error(f"Script not found: {script_path}")
            return False

        cmd = [self.venv_python, script_path] + args
        display_name = os.path.basename(script_path)
        self.logger.info(f"Executor: Launching {display_name} with args {args}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Use communicate to wait for the process to terminate and capture output
            stdout, stderr = process.communicate()
            
            if stdout:
                for line in stdout.splitlines():
                    if line.strip():
                        self.logger.info(f"[{display_name}] {line}")
            
            if stderr:
                for line in stderr.splitlines():
                    if line.strip():
                        self.logger.error(f"[{display_name} ERR] {line}")
            
            if process.returncode == 0:
                self.logger.info(f"Successfully completed: {display_name}")
                return True
            else:
                self.logger.error(f"Execution failed: {display_name} (Exit Code: {process.returncode})")
                return False
                
        except Exception as e:
            self.logger.error(f"Execution ERROR: {display_name} - {str(e)}")
            return False

# --- 2. Abstractions: Scheduling & Management ---

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
    """
    Manages the scheduling logic.
    Wraps the 'schedule' library to provide a standardized interface for pulse cycles.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.schedule = schedule

    def run_pending(self):
        """Executes all pending scheduled tasks."""
        self.schedule.run_pending()


# --- 4. Orchestrator Service ---

class AgentOrchestrator:
    def __init__(self, symbol: str, pulse_minutes: float, data_root: str, mode: str):
        self.data_root = data_root
        self.symbol = symbol
        self.mode = mode
        self.interval_hours = pulse_minutes / 60.0
        log_path = os.path.join(data_root, "agent_orchestrator.log")
        self.logger = setup_logger("AgentOrchestrator", log_file=log_path)
        self.executor = ProcessExecutor(self.logger)
        self.scheduler = JobScheduler(self.logger)
        self.validator = ConfigValidator(self.logger)
        
        # Initialize the Modern Binary Star Orchestrator & Notifier
        try:
            self.config = load_config()
            load_dotenv()
            self.api_key = os.environ.get("GEMINI_API_KEY")
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not found in environment.")
                
            self.orchestrator = BinaryStarOrchestrator(
                config_dict=self.config, 
                api_key=self.api_key, 
                data_root=self.data_root
            )
            self.notifier = StrategyNotifier(data_root=self.data_root)
            self.logger.info("Production BinaryStar Orchestrator & Notifier initialized.")
            
            # Failure tracking for circuit breaker
            self.consecutive_failures = 0
            self.max_failures_threshold = 3
            
            # Use shared scanner (Shared observers mapping topography)
            self.scanner = OpportunityScanner(
                self.symbol, 
                self.data_root, 
                logger=self.logger, 
                observer=self.orchestrator.observer
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize Agent Components: {e}", exc_info=True)
            sys.exit(1)

    def _run_cycle(self):
        """
        Executes a deterministic pulse cycle using the Binary Star Architecture.
        """
        try:
            # Step 1-2: Fact Gathering & Opportunity Check
            self.logger.info("Cycle Start: Gathering market topography...")
            observation = self.scanner.scan()
            
            if "error" in observation:
                self.logger.error(f"Observation failed: {observation['error']}")
                return

            if self.mode == "scan":
                if not self.scanner.should_trigger(observation):
                    return

            # Step 3: Dual-Star Adversarial Reasoning (Truth Bus active)
            self.logger.info(f"Cycle: Triggering Adversarial Debate Flow for {self.symbol}...")
            session_result = self.orchestrator.execute_flow(observation, self.symbol)

            # Step 4: Strategic Notifications
            self.notifier.notify_strategy(self.symbol, session_result)

            # Step 5: Decision Persistence (Forensic Archival)
            output_file = archive_strategy_result(
                symbol=self.symbol,
                timestamp=observation['timestamp'],
                result=session_result,
                data_root=self.data_root,
                target_dir="strategies"
            )
            self.logger.info(f"Strategy archived: {output_file}")

            # Step 6: Trigger Post-Mortem (Independent Subprocess)
            rev_args = ["--data_root", self.data_root]
            self.executor.run_script("reviewer.py", rev_args)
            
            # Reset circuit breaker on success
            self.consecutive_failures = 0

        except Exception as e:
            self.consecutive_failures += 1
            err_msg = f"Cycle execution failed ({self.consecutive_failures}/{self.max_failures_threshold}): {e}"
            self.logger.error(err_msg, exc_info=True)
            
            # Circuit Breaker: Dispatch email on critical failure threshold
            if self.consecutive_failures >= self.max_failures_threshold:
                self.logger.critical("CIRCUIT BREAKER TRIGGERED: Dispatching Emergency Alert.")
                self.notifier.notify_alert(
                    alert_name="PIPELINE_CIRCUIT_BREAKER",
                    symbol=self.symbol,
                    error_message=err_msg,
                    metadata={"total_consecutive_failures": self.consecutive_failures, "symbol": self.symbol}
                )

        finally:
            # Step 7: Resource Hygiene (Mandatory cleanup of Gemini Context Caches)
            try:
                self.orchestrator.cache_manager.delete_market_cache()
                self.logger.info("Cycle Hygiene: Market context cache purged successfully.")
            except Exception as cache_err:
                self.logger.warning(f"Cycle Hygiene: Cache cleanup failed (non-critical): {cache_err}")

    def start(self):
        """Starts the service cycle."""
        self.logger.info(f"=== Starting Agent Orchestrator [{self.mode}] for {self.symbol} ===")
        
        if not self.validator.validate_interval(self.interval_hours):
            self.logger.error("Validation failed. Aborting startup.")
            sys.exit(1)

        # Initial run
        self.logger.info("Executing initial startup run...")
        self._run_cycle()

        if self.mode in ["dry_run", "once"]:
            self.logger.info(f"Execution mode '{self.mode}' complete. Exiting requested.")
            return

        # Schedule
        self.logger.info(f"Scheduling pulse every {self.interval_hours} hours.")
        self.scheduler.schedule.every(self.interval_hours).hours.do(self._run_cycle)

        self.logger.info("Orchestrator monitoring loop active.")
        try:
            while True:
                self.scheduler.run_pending()
                time.sleep(10) # 10s check interval for loop efficiency
        except KeyboardInterrupt:
            self.logger.info("Orchestrator received shutdown signal.")

def main():
    parser = argparse.ArgumentParser(description="SOLID Agent Orchestrator")
    parser.add_argument("--symbol", type=str, help="Symbol to oversee (e.g. BTCUSDT)")
    parser.add_argument("--pulse", type=float, required=True, help="Pipeline interval in minutes")
    parser.add_argument("--mode", type=str, choices=["fix", "scan", "dry_run", "once"], default="once", help="Execution mode (fix: run every pulse, scan: run only when market is interesting, dry_run: test run and exit, once: single production run and exit)")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
    
    # Load global defaults for missing CLI args
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    if not symbol:
        print("Error: Symbol not provided and no default found in global_config.yaml")
        sys.exit(1)
        
    orchestrator = AgentOrchestrator(
        symbol=symbol, 
        pulse_minutes=args.pulse, 
        data_root=data_root,
        mode=args.mode
    )
    orchestrator.start()

if __name__ == "__main__":
    main()
