#!/usr/bin/env python3
import os
import sys
import time
import argparse
from datetime import datetime, timezone

# Setup absolute project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.join(__file__, "../")))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.sniper.scout import SniperScout
from src.sniper.trigger import SniperTrigger
from src.utils.logger_utils import setup_logger

logger = setup_logger("SniperSandbox")

def main():
    # Load global config early to respect user-defined defaults
    from src.utils.pipeline_utils import load_global_config, add_data_path_argument
    global_cfg = load_global_config()
    pulse_mins = global_cfg.get('sniper', {}).get('pulse_interval_minutes')

    parser = argparse.ArgumentParser(description="Singularity Sniper Mode Sandbox (Independent Test)")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix (e.g. BTC)")
    parser.add_argument("--continuous", action="store_true", help="Run continuously using pulse_interval_minutes from config")
    parser.add_argument("--email", action="store_true", help="Send email notification on trigger")
    
    add_data_path_argument(parser)
    
    args = parser.parse_args()
    
    # v7.1: ZERO-ENTROPY PATH RESOLUTION
    # Use the standardized path if provided, otherwise default to config-level prod.
    if not args.path:
        args.path = "data/prod"
    data_root = args.path
    
    # Re-initialize logger with file support relative to data_root
    log_file = os.path.join(data_root, "sniper_sandbox.log")
    setup_logger("SniperSandbox", log_file=log_file)
    
    from src.utils.symbol_utils import resolve_symbol
    scout = SniperScout(resolve_symbol(args.symbol))
    trigger = SniperTrigger()
    
    prev_metrics = None
    
    logger.info(f"--- Sniper Sandbox Initialized: {args.symbol} (Path: {data_root}, Continuous: {args.continuous}) ---")
    
    try:
        while True:
            # 1. Harvest Data (No Images)
            result = scout.scout()
            metrics = result.metrics
            
            # 2. Evaluate Matrix
            is_noteworthy, t_type, reason = trigger.evaluate(metrics, prev_metrics)
            
            # 3. Report
            if is_noteworthy:
                print("\n" + "="*50)
                print(f"       🔫 SNIPER WAKE UP! [{t_type}]")
                print("="*50)
                print(f"REASON: {reason}")
                print("="*50 + "\n")
                
                logger.info(f"Trigger Detail: {reason}")
                trigger.set_triggered(t_type)

                # 4. Email Alert Lifecycle
                if args.email:
                    from src.infrastructure.notifications.base_notifier import EmailDispatcher, NotificationConfig, BaseEmailTemplate
                    from src.utils.datetime_utils import to_html_display
                    
                    config = NotificationConfig.from_env()
                    if config.enabled:
                        dispatcher = EmailDispatcher(config)
                        now_str = datetime.now(timezone.utc).isoformat()
                        
                        # v7.1: Specialized Chinese Type Explanations
                        TYPE_DESC = {
                            "TYPE_A (Breakout)": "<b>势能破局</b> - 检测到波动率爆发或物理挤压，代表盘面即将变盘，势能正在从静默转向发力。",
                            "TYPE_B (Asymmetry)": "<b>动能失衡</b> - 监测到显著的机构资金流向或散户情绪偏振，代表市场内部力量对比发生剧烈倾斜。",
                            "TYPE_C (Structural)": "<b>关键拓扑</b> - 价格运行至筹码密集区边界、POC磁吸点或爆仓密集区，代表正在测试关键支撑或阻力结构。"
                        }
                        type_desc_zh = TYPE_DESC.get(t_type, "未知信号类型")

                        subject = f"🔫 [SANDBOX] Sniper Trigger: {args.symbol} | {t_type}"
                        
                        html_body = f"""
                        <html>
                        <head>{BaseEmailTemplate.get_styles()}</head>
                        <body>
                            <div class="container">
                                <div style="text-align: center; margin-bottom: 25px; border-bottom: 2px solid #f1f5f9; padding-bottom: 15px;">
                                    <div style="display: inline-block; padding: 4px 12px; border-radius: 50px; background-color: #3b82f615; color: #3b82f6; font-weight: 700; font-size: 11px; margin-bottom: 8px;">
                                        🎯 SNIPER SANDBOX SIGNAL
                                    </div>
                                    <h1 style="color: #0f172a; margin: 0; font-size: 24px;">{args.symbol} 信号触发</h1>
                                    <p style="color: #64748b; font-size: 13px;">检测时间: {to_html_display(now_str)}</p>
                                </div>
                                
                                <div class="panel" style="background-color: #f8fafc; border-left: 4px solid #3b82f6;">
                                    <h3 class="panel-title">📡 触发详情 (Trigger Details)</h3>
                                    <p style="font-size: 14px; margin-bottom: 10px;"><b>信号类型:</b> {t_type}</p>
                                    <p style="font-size: 14px; margin-bottom: 15px; color: #334155; line-height: 1.5; background: #eff6ff; padding: 10px; border-radius: 6px;">
                                        {type_desc_zh}
                                    </p>
                                    <p style="font-size: 14px; margin-bottom: 5px;"><b>判定逻辑 (Reasoning):</b></p>
                                    <div style="background: #ffffff; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; font-size: 13px; line-height: 1.6;">
                                        {BaseEmailTemplate.render_md(reason)}
                                    </div>
                                </div>
                                
                                <div style="margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 15px; text-align: center; color: #94a3b8; font-size: 10px;">
                                    This is an auto-generated email notification | Triggered by Singularity
                                </div>
                            </div>
                        </body>
                        </html>
                        """
                        
                        if dispatcher.dispatch(subject, html_body):
                            logger.info(f"Sandbox: Email alert dispatched for {args.symbol}.")
                        else:
                            logger.warning("Sandbox: Email dispatch failed. Check credentials.")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 💤 SLEEPING | No actionable asymmetry.")
            
            # 4. Loop Logic
            if not args.continuous:
                break
                
            prev_metrics = metrics
            logger.info(f"Waiting {pulse_mins}m for next scout...")
            time.sleep(pulse_mins * 60)
            
    except KeyboardInterrupt:
        logger.warning("Sniper Sandbox terminated by user.")
    finally:
        scout.close()

if __name__ == "__main__":
    main()
