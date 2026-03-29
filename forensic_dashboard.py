#!/usr/bin/env python3
import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Path normalization for internal imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.agent_utils import load_global_config
from src.utils.json_utils import load_json
from src.utils.logger_utils import setup_logger
from src.utils.path_utils import resolve_project_root
from src.infrastructure.notifications.email_notifier import StrategyNotifier

# Initialize Dashboard logger
logger = setup_logger("ForensicDashboard", log_level=logging.INFO)

# ==========================================
# 1. HTML/JS/CSS Template (Embedded Tailwind & Chart.js)
# ==========================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Strategic Alpha Ledger: {{SYMBOL}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui, sans-serif; }
        .card { background-color: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; padding: 1.5rem; }
        pre::-webkit-scrollbar { height: 8px; }
        pre::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
    </style>
</head>
<body class="p-6 md:p-10">
    <div class="max-w-7xl mx-auto space-y-6">
        
        <div class="flex justify-between items-end border-b border-slate-700 pb-4">
            <div>
                <h1 class="text-2xl font-bold text-slate-100">{{SYMBOL}} Ledger</h1>
                <p class="text-slate-400 text-sm mt-1" id="gen-time-label">Generated: --</p>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="card">
                <div class="text-slate-400 text-xs font-semibold uppercase">Validated Samples (TP + SL + NEITHER)</div>
                <div class="text-3xl font-bold mt-1 text-slate-200" id="kpi-executed">0</div>
            </div>
            <div class="card">
                <div class="text-slate-400 text-xs font-semibold uppercase">Win Rate (TP / Total Validated)</div>
                <div class="text-3xl font-bold mt-1 text-emerald-400" id="kpi-winrate">0%</div>
            </div>
            <div class="card">
                <div class="text-slate-400 text-xs font-semibold uppercase">Cumulative Net PnL (%)</div>
                <div class="text-3xl font-bold mt-1 text-purple-400" id="kpi-pnl">0.00%</div>
            </div>
        </div>

        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Samples Distribution</h2>
            <p class="text-xs text-slate-400 mb-4">Bubble Radius = Target Holding Time | Green: TP_HIT | Red: SL_HIT | Gray: EXPIRED/NEITHER</p>
            <div class="relative h-[450px]">
                <canvas id="timelineChart"></canvas>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="card">
                <h2 class="text-lg font-semibold mb-4 text-slate-200">Confidence Threshold Optimizer</h2>
                <p class="text-xs text-slate-400 mb-4">PnL simulation restricted to signals with Confidence >= X.</p>
                <div class="relative h-[300px]">
                    <canvas id="optimizerChart"></canvas>
                </div>
            </div>
            <div class="card">
                <h2 class="text-lg font-semibold mb-4 text-slate-200">Confidence Score Distribution</h2>
                <p class="text-xs text-slate-400 mb-4">Quantized distribution of model confidence across the period.</p>
                <div class="relative h-[300px]">
                    <canvas id="distChart"></canvas>
                </div>
            </div>
        </div>

        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Raw Data</h2>
            <div class="bg-slate-900 rounded-lg p-4 overflow-x-auto">
                <pre><code class="text-xs font-mono text-emerald-300" id="json-dump"></code></pre>
            </div>
        </div>

    </div>

    <script>
        const RAW_DATA = {{JSON_DATA}};
        
        // 1. Render Local Generation Time with Timezone Abbreviation
        const now = new Date();
        const genTimeStr = now.toLocaleString('en-GB', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false }).replace(',', '');
        
        // Robust way to get 'NZDT' style abbreviations
        let tzName = 'Local';
        try {
            const fullStr = now.toString(); // e.g., "... (New Zealand Daylight Time)"
            const match = fullStr.match(/\(([^)]+)\)$/);
            if (match) {
                const longName = match[1];
                // Check if it's already an abbreviation (like "NZDT" or "NZST")
                if (longName.length <= 5 && /^[A-Z]+$/.test(longName)) {
                    tzName = longName;
                } else {
                    // Convert "New Zealand Daylight Time" -> "NZDT"
                    // Filter out non-capitalized words like 'of', 'the'
                    tzName = longName.split(' ')
                        .filter(word => word.length > 0 && /^[A-Z]/.test(word))
                        .map(word => word[0])
                        .join('')
                        .toUpperCase();
                }
            }
        } catch(e) {}
        
        document.getElementById('gen-time-label').innerText = `Generated: ${genTimeStr} ${tzName}`;

        // 2. Render JSON Dump
        document.getElementById('json-dump').textContent = JSON.stringify(RAW_DATA, null, 2);

        // 3. Compute KPIs
        const executedTrades = RAW_DATA.filter(d => d.tp_sl_result === 'TP_HIT' || d.tp_sl_result === 'SL_HIT' || d.tp_sl_result === 'NEITHER');
        const wins = executedTrades.filter(d => d.tp_sl_result === 'TP_HIT');
        
        let netPnl = 0;
        executedTrades.forEach(t => netPnl += t.estimated_pnl_pct);

        document.getElementById('kpi-executed').innerText = executedTrades.length;
        document.getElementById('kpi-winrate').innerText = executedTrades.length > 0 ? ((wins.length / executedTrades.length) * 100).toFixed(1) + '%' : '0%';
        
        const pnlEl = document.getElementById('kpi-pnl');
        pnlEl.innerText = (netPnl > 0 ? '+' : '') + netPnl.toFixed(2) + '%';
        pnlEl.className = netPnl >= 0 ? 'text-3xl font-bold mt-1 text-emerald-400' : 'text-3xl font-bold mt-1 text-rose-400';

        // 4. Timeline Bubble Chart (Temporal)
        const bubbleData = RAW_DATA.map((d) => {
            let color = 'rgba(148, 163, 184, 0.6)'; // Gray (Neutral/expired)
            if (d.tp_sl_result === 'TP_HIT') color = 'rgba(52, 211, 153, 0.7)'; // Emerald
            if (d.tp_sl_result === 'SL_HIT') color = 'rgba(251, 113, 133, 0.7)'; // Rose
            
            const r = Math.max(5, Math.min(30, (d.holding_time_hours || 1) * 2));
            
            return {
                x: d.observation_time,
                y: d.confidence,
                r: r,
                label: d.name,
                pnl: d.estimated_pnl_pct,
                holding: d.holding_time_hours,
                color: color
            };
        });

        // Calculate absolute temporal bounds
        const allTimes = RAW_DATA.map(d => new Date(d.observation_time).getTime());
        const allEndTimes = RAW_DATA.map(d => new Date(d.observation_time).getTime() + (d.holding_time_hours || 0) * 3600000);
        const minTime = Math.min(...allTimes) - (2 * 3600000); // 2h buffer before
        const maxTime = Math.max(...allEndTimes) + (2 * 3600000); // 2h buffer after

        new Chart(document.getElementById('timelineChart'), {
            type: 'bubble',
            data: {
                datasets: [{
                    label: 'Trade Signals',
                    data: bubbleData,
                    backgroundColor: bubbleData.map(d => d.color),
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const d = ctx.raw;
                                return [`${d.label}`, `Confidence: ${d.y}%`, `PnL: ${d.pnl.toFixed(2)}%`, `Holding: ${d.holding.toFixed(1)} hours`];
                            }
                        }
                    }
                },
                scales: {
                    x: { 
                        type: 'time',
                        min: minTime,
                        max: maxTime,
                        time: { unit: 'hour', displayFormats: { hour: 'MMM dd, HH:mm' } },
                        ticks: { color: '#64748b' }, 
                        grid: { color: '#334155' }, 
                        title: { display: true, text: `Market Capture Timestamp (${tzName})`, color: '#94a3b8'} 
                    },
                    y: { min: 40, max: 100, ticks: { color: '#64748b' }, grid: { color: '#334155' }, title: { display: true, text: 'Model Confidence (%)', color: '#94a3b8'} }
                }
            }
        });

        // 5. Threshold Optimizer Chart
        const thresholds = [];
        const pnlAtThresholds = [];
        
        for (let t = 40; t <= 100; t += 5) {
            let pnlSum = 0;
            executedTrades.forEach(trade => {
                if (trade.confidence >= t) {
                    pnlSum += trade.estimated_pnl_pct;
                }
            });
            thresholds.push(t);
            pnlAtThresholds.push(pnlSum);
        }

        new Chart(document.getElementById('optimizerChart'), {
            type: 'line',
            data: {
                labels: thresholds,
                datasets: [{
                    label: 'Cumulative PnL (%)',
                    data: pnlAtThresholds,
                    borderColor: '#60a5fa', 
                    backgroundColor: 'rgba(96, 165, 250, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: '#64748b' }, grid: { display: false }, title: { display: true, text: 'Min Confidence Threshold (%)', color: '#94a3b8'} },
                    y: { ticks: { color: '#64748b' }, grid: { color: '#334155' } }
                }
            }
        });

        // 6. Confidence Distribution (5pt Bins)
        const bins = [];
        for (let i = 40; i <= 95; i += 5) {
            const label = i === 95 ? "95-100" : `${i}-${i+4}`;
            bins.push({ label: label, min: i, max: i === 95 ? 100 : i+4, count: 0 });
        }
        executedTrades.forEach(s => {
            const c = s.confidence;
            bins.forEach(b => {
                if (c >= b.min && c <= b.max) b.count++;
            });
        });

        new Chart(document.getElementById('distChart'), {
            type: 'bar',
            data: {
                labels: bins.map(b => b.label),
                datasets: [{
                    label: 'Frequency',
                    data: bins.map(b => b.count),
                    backgroundColor: '#8b5cf6', 
                    borderRadius: 4,
                    barPercentage: 0.7
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#64748b' }, grid: { display: false } },
                    y: { ticks: { color: '#64748b', stepSize: 1 }, grid: { color: '#334155' } }
                }
            }
        });

        new Chart(document.getElementById('distChart'), {
            type: 'bar',
            data: {
                labels: bins.map(b => b.label),
                datasets: [{
                    label: 'Frequency',
                    data: bins.map(b => b.count),
                    backgroundColor: '#8b5cf6', 
                    borderRadius: 4,
                    barPercentage: 0.7
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#64748b' }, grid: { display: false } },
                    y: { ticks: { color: '#64748b', stepSize: 1 }, grid: { color: '#334155' } }
                }
            }
        });
    </script>
</body>
</html>
"""

class ForensicDashboardGenerator:
    """
    Scans forensic review reports and generates a high-dimensional HTML dashboard.
    """
    def __init__(self, data_root: str):
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.logger = logger
        # To avoid confusion with relative pathing in notifier
        self.notifier = StrategyNotifier(data_root=data_root)

    def generate(self, symbol: str):
        """Main execution flow for report generation."""
        self.logger.info(f"Scanning for {symbol} forensic evidence in {self.data_root}...")
        
        dataset = self._extract_data(symbol)
        if not dataset:
            self.logger.warning(f"No valid forensic reports found for {symbol}. Sidestepping dashboard generation.")
            return

        self.logger.info(f"Analyzed {len(dataset)} forensic records. Assembling HTML Dashboard...")
        output_path = self._write_html(symbol, dataset)
        
        # 3. Dispatch automated notification
        try:
            self.notifier.notify_dashboard(symbol, dataset, dashboard_path=output_path)
        except Exception as e:
            self.logger.error(f"Failed to dispatch dashboard notification: {e}")

    def _extract_data(self, symbol: str) -> List[Dict[str, Any]]:
        """Parses JSON review reports recursively and extracts normalized performance telemetry."""
        reviewers_root = os.path.join(self.data_root, "reviewers")
        if not os.path.exists(reviewers_root):
            self.logger.warning(f"Reviewers directory not found: {reviewers_root}")
            return []

        extracted_data = []
        processed_filenames = set()
        
        # Keyword and Symbol filter
        prefix = f"{symbol}_reviewers_"
        
        self.logger.info(f"Scanning root of {reviewers_root}...")

        # Non-recursive scan of the root folder specifically
        files = [f for f in os.listdir(reviewers_root) if os.path.isfile(os.path.join(reviewers_root, f))]
        
        for filename in sorted(files):
            if not filename.endswith(".json") or not filename.startswith(prefix):
                continue
            
            filepath = os.path.join(reviewers_root, filename)
            data = load_json(filepath)
            if not data:
                continue

            # 2. Core logic: Filter for finalized orders
            market_outcome = data.get("market_outcome", {})
            intercept = market_outcome.get("intercept_status", {})
            
            # 1. Skip if intercepted (STUB/PENDING)
            if intercept.get("is_intercepted", False):
                self.logger.info(f"Skipping intercepted session: {filename} ({intercept.get('reason')})")
                continue

            # Extract Strategy metadata
            session = data.get("strategy_session", {})
            obs = session.get("observation", {})
            start_time = obs.get("timestamp")
            
            final_decision = session.get("final_decision", {})
            opinion = final_decision.get("opinion", "NEUTRAL")

            # 2. 只包含原策略 final_decision.opinion 是 BULLISH 或者 BEARISH 的
            if opinion not in ["BULLISH", "BEARISH"]:
                self.logger.info(f"Skipping non-trading decision: {filename} (Opinion: {opinion})")
                continue

            confidence = final_decision.get("confidence")
            limit_order = final_decision.get("limit_order", {})
            holding_time_hours = limit_order.get("holding_time_hours", 0)
            est_pnl_pct = 0.0
            
            entry = float(limit_order.get("entry", 0))
            tp = float(limit_order.get("take_profit", 0))
            sl = float(limit_order.get("stop_loss", 0))
            
            if entry > 0:
                if tp_sl_result == "TP_HIT":
                    est_pnl_pct = abs(tp - entry) / entry * 100
                elif tp_sl_result == "SL_HIT":
                    est_pnl_pct = -abs(entry - sl) / entry * 100

            extracted_data.append({
                "name": filename,
                "observation_time": start_time,
                "holding_time_hours": holding_time_hours,
                "tp_sl_result": tp_sl_result,
                "estimated_pnl_pct": round(float(est_pnl_pct), 2),
                "confidence": confidence
            })
            
        # Ensure chronological order based on observation time
        extracted_data.sort(key=lambda x: x['observation_time'] if x['observation_time'] else "")
        return extracted_data

    def _write_html(self, symbol: str, dataset: List[Dict[str, Any]]):
        """Injects dataset into the HTML template and saves the result."""
        html_dir = os.path.join(self.data_root, "html")
        os.makedirs(html_dir, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_filename = f"{symbol}_dashboard_{ts}.html"
        output_path = os.path.join(html_dir, output_filename)

        # Token replacement
        content = HTML_TEMPLATE.replace("{{SYMBOL}}", symbol)
        content = content.replace("{{GENERATION_TIME}}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        content = content.replace("{{JSON_DATA}}", json.dumps(dataset))

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.logger.info(f"Forensic Alpha Matrix generated: {output_path}")
        return output_path

def main():
    parser = argparse.ArgumentParser(description="Forensic Performance & Confidence Analyzer")
    parser.add_argument("--symbol", type=str, help="Symbol to filter")
    
    from src.utils.agent_utils import add_data_root_argument, resolve_data_root
    add_data_root_argument(parser)
    
    args = parser.parse_args()
    
    # Resolve data_root
    data_root = args.data_root or resolve_data_root(args.env_shortcut)
    if not data_root:
        print("Error: --data_root or environment shortcut (e.g., prod, live) must be provided.")
        sys.exit(1)
        
    global_cfg = load_global_config()
    symbol = args.symbol or global_cfg['system']['default_symbol']
    
    try:
        generator = ForensicDashboardGenerator(data_root=data_root)
        generator.generate(symbol)
    except Exception as e:
        logger.error(f"Dashboard Generation Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
