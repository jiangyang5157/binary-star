#!/usr/bin/env python3
import os
import sys
import argparse

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

from src.analyzer.forensic_controller import ForensicController
from src.utils.pipeline_utils import load_config, setup_logger

# Initialize CLI-level logger
logger = setup_logger("ManualAudit")

def main():
    parser = argparse.ArgumentParser(description="Thin CLI Wrapper for Forensic Audit (v5.3)")
    parser.add_argument("--file", required=True, help="Path to strategy JSON")
    args = parser.parse_args()
    
    config = load_config()
    controller = ForensicController(config_dict=config, logger=logger)
    
    try:
        # Delegate logic to controller
        result = controller.run_manual_audit(args.file)
        outcome = result['outcome']
        report = result['report']
        
        # Consistent result output
        print("\n" + "="*50)
        print(f"FORENSIC REPORT: {result['symbol']}")
        print("="*50)
        print(f"RESULT: {outcome['tp_sl_result']}")
        print(f"IS_FILLED: {outcome['is_filled']}")
        
        status = report['forensic_status']
        print(f"\nJUSTIFIED_SURRENDER: {status['is_justified_surrender']}")
        print(f"MAE_STRESS_TIER: {status['mae_stress_tier']}")
        
        if outcome['is_filled']:
            m = outcome['trade_execution_metrics']
            print(f"MAE_STRESS: {m['mae_stress_level_pct']}%")
            print(f"MFE_EFFICIENCY: {m['mfe_efficiency_pct']}%")
        
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"Manual Audit Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
