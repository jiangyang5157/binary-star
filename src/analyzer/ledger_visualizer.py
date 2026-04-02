import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.utils.json_utils import load_json
from src.utils.path_utils import resolve_project_root
from src.infrastructure.notifications.email_notifier import StrategyNotifier


class LedgerVisualizer:
    """Consolidated Logic for Execution Monitoring & Visualization."""
    def __init__(self, data_root: str, logger: logging.Logger):
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.logger = logger
        self.notifier = StrategyNotifier(data_root=data_root)

    def generate_html_report(self, symbol: str, notify: bool = False, recursive: bool = False):
        """Orchestrates path scanning, data extraction, and HTML rendering."""
        self.logger.info(f"Scanning for {symbol} evidence in {self.data_root}...")
        dataset = self._extract_data(symbol, recursive)
        
        if not dataset:
            self.logger.warning("No audit reports found. Skipping visualizer.")
            return None

        # 1. Inject Data -> 2. Write File
        html_dir = os.path.join(self.data_root, "html")
        os.makedirs(html_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(html_dir, f"{symbol}_ledger_{ts}.html")
        
        content = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Strategic Dashboard: {{SYMBOL}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui, sans-serif; }
        .card { background-color: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; padding: 1.5rem; }
    </style>
</head>
<body class="p-6 md:p-10">
    <div class="max-w-7xl mx-auto space-y-6">
        <div class="flex justify-between items-end border-b border-slate-700 pb-4">
            <div>
                <h1 class="text-2xl font-bold text-slate-100">{{SYMBOL}} Execution Dashboard</h1>
                <p class="text-slate-400 text-sm mt-1" id="gen-time-label">Generated: --</p>
            </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Executed / Total</div><div class="text-3xl font-bold mt-1 text-slate-200" id="kpi-executed">0</div></div>
            <div class="card border-l-4 border-emerald-500"><div class="text-slate-400 text-xs font-semibold uppercase">Calmar Ratio</div><div class="text-3xl font-bold mt-1 text-emerald-400" id="kpi-calmar">0.00</div></div>
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Max Drawdown (%)</div><div class="text-3xl font-bold mt-1 text-rose-400" id="kpi-mdd">0.00%</div></div>
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Equity Growth (%)</div><div class="text-3xl font-bold mt-1 text-purple-400" id="kpi-pnl">0.00%</div></div>
        </div>
        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Audit Timeline</h2>
            <div class="relative h-[450px]"><canvas id="timelineChart"></canvas></div>
        </div>
        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Equity Growth (%) Curve</h2>
            <div class="relative h-[350px]"><canvas id="equityChart"></canvas></div>
        </div>
        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Raw Summary</h2>
            <div class="bg-slate-900 rounded-lg p-4 overflow-x-auto"><pre><code class="text-xs font-mono text-emerald-300" id="json-dump"></code></pre></div>
        </div>
    </div>
    <script>
        const RAW_DATA = {{JSON_DATA}};
        document.getElementById('gen-time-label').innerText = `Generated: ${new Date().toLocaleString()}`;
        document.getElementById('json-dump').textContent = JSON.stringify(RAW_DATA, null, 2);
        const sortedTrades = [...RAW_DATA].sort((a, b) => new Date(a.observation_time) - new Date(b.observation_time));
        const executedTrades = sortedTrades.filter(d => d.is_filled);
        let eq = 1.0, peak = 1.0, dd = 0;
        const curve = [];
        executedTrades.forEach(t => {
            eq *= (1 + t.estimated_pnl_pct / 100.0);
            if (eq > peak) peak = eq;
            dd = Math.max(dd, (peak - eq) / peak);
            curve.push({ x: t.observation_time, y: (eq - 1) * 100 });
        });
        document.getElementById('kpi-executed').innerText = `${executedTrades.length} / ${RAW_DATA.length}`;
        document.getElementById('kpi-mdd').innerText = (dd * 100).toFixed(2) + '%';
        document.getElementById('kpi-pnl').innerText = ((eq - 1) * 100).toFixed(2) + '%';
        const bubble = RAW_DATA.map(d => ({
            x: d.observation_time, y: d.confidence,
            r: Math.max(5, Math.min(30, (d.holding_time_hours || 1) * 2)),
            color: d.tp_sl_result === 'TP_HIT' ? 'rgba(52, 211, 153, 0.7)' : d.tp_sl_result === 'SL_HIT' ? 'rgba(251, 113, 133, 0.7)' : d.is_filled ? 'rgba(71, 85, 105, 0.6)' : 'rgba(148, 163, 184, 0.4)'
        }));
        const scales = { x: { type: 'time', time: { unit: 'hour' }, ticks: { color: '#64748b' }, grid: { color: '#334155' } }, y: { ticks: { color: '#64748b' }, grid: { color: '#334155' } } };
        new Chart(document.getElementById('timelineChart'), { type: 'bubble', data: { datasets: [{ data: bubble, backgroundColor: bubble.map(d => d.color) }] }, options: { responsive: true, maintainAspectRatio: false, scales: scales } });
        new Chart(document.getElementById('equityChart'), { type: 'line', data: { datasets: [{ data: curve, borderColor: '#a78bfa', fill: true, backgroundColor: 'rgba(167, 139, 250, 0.1)' }] }, options: { responsive: true, maintainAspectRatio: false, scales: scales } });
    </script>
</body></html>""".replace("{{SYMBOL}}", symbol).replace("{{JSON_DATA}}", json.dumps(dataset))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.logger.info(f"Ledger Visualizer: Report successfully rendered to {output_path}")
        
        if notify:
            self.notifier.notify_ledger(symbol, dataset, ledger_path=output_path)
        
        return output_path

    def _extract_data(self, symbol: str, recursive: bool) -> List[Dict[str, Any]]:
        """Parses JSON audit reports and extracts normalized performance telemetry."""
        audits_root = os.path.join(self.data_root, "audits")
        if not os.path.exists(audits_root): return []

        extracted = []
        prefix = f"{symbol}_audit_"
        
        all_files = []
        if recursive:
            for root, _, files in os.walk(audits_root):
                for f in files: all_files.append((root, f))
        else:
            all_files = [(audits_root, f) for f in os.listdir(audits_root) if os.path.isfile(os.path.join(audits_root, f))]

        for root, filename in sorted(all_files, key=lambda x: x[1]):
            if not filename.endswith(".json") or not filename.startswith(prefix): continue
            
            data = load_json(os.path.join(root, filename))
            if not data: continue

            # Core filtering logic
            outcome = data.get("market_outcome", {})
            if outcome.get("intercept_status", {}).get("is_intercepted"): continue

            session = data.get("strategy_session", {})
            fd = session.get("final_decision", {})
            if fd.get("opinion") not in ["BULLISH", "BEARISH"]: continue

            lo = fd.get("limit_order", {})
            entry = float(lo.get("entry", 0))
            res = outcome.get("tp_sl_result", "NEITHER")
            pnl = 0.0
            if entry > 0:
                if res == "TP_HIT": pnl = abs(float(lo.get("take_profit", 0)) - entry) / entry * 100
                elif res == "SL_HIT": pnl = -abs(entry - float(lo.get("stop_loss", 0))) / entry * 100

            extracted.append({
                "observation_time": session.get("observation", {}).get("timestamp"),
                "is_filled": outcome.get("is_filled", False),
                "tp_sl_result": res,
                "estimated_pnl_pct": round(pnl, 2),
                "confidence": fd.get("confidence", 0),
                "holding_time_hours": lo.get("holding_time_hours", 0)
            })
            
        extracted.sort(key=lambda x: x['observation_time'] or "")
        return extracted
