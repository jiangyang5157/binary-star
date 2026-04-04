import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.utils.json_utils import load_json
from src.utils.path_utils import resolve_project_root
from src.utils.datetime_utils import to_html_display
from src.infrastructure.notifications.email_notifier import SessionNotifier


class LedgerVisualizer:
    """Consolidated Logic for Execution Monitoring & Visualization."""
    def __init__(self, data_root: str, logger: logging.Logger):
        self.data_root = os.path.join(resolve_project_root(), data_root)
        self.logger = logger
        self.notifier = SessionNotifier(data_root=data_root)

    def generate_html_report(self, symbol: str, notify: bool = False, recursive: bool = False):
        """Orchestrates path scanning, data extraction, and HTML rendering."""
        self.logger.info(f"Scanning for {symbol} evidence in {self.data_root}...")
        dataset = self._extract_data(symbol, recursive)
        
        if not dataset:
            self.logger.warning("No audit reports found. Skipping visualizer.")
            return None

        return self._render_html(symbol, dataset, notify)

    def generate_from_sandbox_file(self, file_path: str, symbol: str, notify: bool = False):
        """Parses a Sandbox result JSON directly and renders a strategy/ledger dashboard."""
        self.logger.info(f"Extracting forensic cases from sandbox: {file_path}")
        data = load_json(file_path)
        if not data:
            self.logger.error(f"Failed to load sandbox file: {file_path}")
            return None
        
        # Merge all cases (Accepted + Rejected) to see the full evolutionary spectrum
        all_cases = data.get("accepted_cases", []) + data.get("rejected_cases", [])
        dataset = []
        for case in all_cases:
            norm = self._normalize_audit_report(case)
            if norm: dataset.append(norm)
            
        if not dataset:
            self.logger.warning(f"No valid trading cases found in sandbox {file_path}")
            return None

        # Sort chronologically
        dataset.sort(key=lambda x: x['observation_time'] or "")
        return self._render_html(symbol, dataset, notify)

    def _render_html(self, symbol, dataset, notify=False):
        """Internal rendering engine for Ledger Dashboards."""
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
                <h1 class="text-2xl font-bold text-slate-100">{{SYMBOL}} Ledger Dashboard</h1>
                <p class="text-slate-400 text-sm mt-1" id="gen-time-label">Generated at: {{GEN_TIME}}</p>
            </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Executed / Total</div><div class="text-3xl font-bold mt-1 text-slate-200" id="kpi-executed">0</div></div>
            <div class="card border-l-4 border-emerald-500"><div class="text-slate-400 text-xs font-semibold uppercase">Calmar Ratio</div><div class="text-3xl font-bold mt-1 text-emerald-400" id="kpi-calmar">0.00</div></div>
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Max Drawdown (%)</div><div class="text-3xl font-bold mt-1 text-rose-400" id="kpi-mdd">0.00%</div></div>
            <div class="card"><div class="text-slate-400 text-xs font-semibold uppercase">Equity Growth (%)</div><div class="text-3xl font-bold mt-1 text-purple-400" id="kpi-pnl">0.00%</div></div>
        </div>
        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Decision Timeline</h2>
            <p class="text-xs text-slate-400 mb-4">Y-axis = Confidence | Bubble Size = Abs(PnL %) | Color = Outcome</p>
            <div class="relative h-[450px]"><canvas id="timelineChart"></canvas></div>
        </div>
        <div class="card">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">Equity Growth (%) Curve</h2>
            <div class="relative h-[350px]"><canvas id="equityChart"></canvas></div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="card">
                <h2 class="text-lg font-semibold mb-4 text-slate-200">Confidence Threshold Optimizer</h2>
                <p class="text-xs text-slate-400 mb-4">Simulated Cumulative PnL if only signals with Confidence >= X were executed.</p>
                <div class="relative h-[350px]"><canvas id="optimizerChart"></canvas></div>
            </div>
            <div class="card">
                <h2 class="text-lg font-semibold mb-4 text-slate-200">Confidence Score Distribution</h2>
                <p class="text-xs text-slate-400 mb-4">Frequency of confidence scores across the period.</p>
                <div class="relative h-[350px]"><canvas id="distChart"></canvas></div>
            </div>
        </div>
    </div>
    <script>
        const RAW_DATA = {{JSON_DATA}};
        const sortedTrades = [...RAW_DATA].sort((a, b) => new Date(a.observation_time) - new Date(b.observation_time));
        
        // --- Metric Calculation ---
        const executedTrades = sortedTrades.filter(d => d.is_filled);
        let eq = 1.0, peak = 1.0, dd = 0;
        const curve = [];
        executedTrades.forEach(t => {
            eq *= (1 + t.estimated_pnl_pct / 100.0);
            if (eq > peak) peak = eq;
            dd = Math.max(dd, (peak - eq) / peak);
            curve.push({ x: t.observation_time, y: (eq - 1) * 100 });
        });
        
        const netPnL = (eq - 1) * 100;
        const mddPct = dd * 100;
        const calmar = mddPct > 0 ? (netPnL / mddPct) : 0;

        document.getElementById('kpi-executed').innerText = `${executedTrades.length} / ${RAW_DATA.length}`;
        document.getElementById('kpi-mdd').innerText = mddPct.toFixed(2) + '%';
        document.getElementById('kpi-pnl').innerText = netPnL.toFixed(2) + '%';
        document.getElementById('kpi-calmar').innerText = calmar.toFixed(2);

        // --- Chart Configuration ---
        const scales = { 
            x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM dd' } }, ticks: { color: '#64748b', maxRotation: 0 }, grid: { color: '#334155' } }, 
            y: { ticks: { color: '#64748b' }, grid: { color: '#334155' } } 
        };
        const commonOptions = { responsive: true, maintainAspectRatio: false, scales: scales, plugins: { legend: { display: false } } };

        // 1. Decision Timeline (Bubble)
        const bubble = RAW_DATA.map(d => ({
            x: d.observation_time, 
            y: d.confidence,
            r: Math.max(8, Math.min(25, Math.abs(d.estimated_pnl_pct) * 8 + (d.confidence / 10))), // Balanced Size
            pnl: d.estimated_pnl_pct,
            res: d.tp_sl_result,
            holding: d.holding_time_hours,
            color: d.tp_sl_result === 'TP_HIT' ? 'rgba(52, 211, 153, 0.85)' : d.tp_sl_result === 'SL_HIT' ? 'rgba(251, 113, 133, 0.85)' : d.is_filled ? 'rgba(71, 85, 105, 0.7)' : 'rgba(148, 163, 184, 0.3)'
        }));
        
        new Chart(document.getElementById('timelineChart'), { 
            type: 'bubble', 
            data: { datasets: [{ data: bubble, backgroundColor: bubble.map(d => d.color) }] }, 
            options: { 
                ...commonOptions, 
                plugins: { 
                    legend: { display: false },
                    tooltip: { 
                        callbacks: { 
                            label: (ctx) => {
                                const d = ctx.raw;
                                return [`PnL: ${d.pnl > 0 ? '+' : ''}${d.pnl}%`, `Holding: ${d.holding}h` ];
                            } 
                        } 
                    } 
                } 
            } 
        });

        // 2. Equity Curve
        new Chart(document.getElementById('equityChart'), { 
            type: 'line', 
            data: { datasets: [{ data: curve, borderColor: '#a78bfa', borderWidth: 3, pointRadius: 4, pointBackgroundColor: '#a78bfa', fill: true, backgroundColor: 'rgba(167, 139, 250, 0.05)' }] }, 
            options: commonOptions 
        });

        // 3. Confidence Threshold Optimizer
        const thresholds = [], optimizerData = [];
        for (let t = 40; t <= 100; t += 5) {
            let pnlSum = 0;
            executedTrades.forEach(trade => { if (trade.confidence >= t) pnlSum += trade.estimated_pnl_pct; });
            thresholds.push(t);
            optimizerData.push(pnlSum);
        }
        new Chart(document.getElementById('optimizerChart'), {
            type: 'line',
            data: { labels: thresholds, datasets: [{ data: optimizerData, borderColor: '#60a5fa', backgroundColor: 'rgba(96, 165, 250, 0.1)', borderWidth: 3, fill: true, tension: 0.3 }] },
            options: { ...commonOptions, scales: { x: { title: { display: true, text: 'Min Confidence Threshold (%)', color: '#94a3b8' }, ticks: { color: '#64748b' } }, y: { ticks: { color: '#64748b' }, grid: { color: '#334155' } } } }
        });

        // 4. Confidence Distribution
        const bins = [];
        for (let i = 40; i <= 95; i += 5) { bins.push({ label: `${i}-${i+4}`, min: i, max: i+4, count: 0, pnl_sum: 0 }); }
        executedTrades.forEach(s => { 
            bins.forEach(b => { 
                if (s.confidence >= b.min && s.confidence <= b.max) {
                    b.count++; 
                    b.pnl_sum += s.estimated_pnl_pct;
                }
            }); 
        });
        new Chart(document.getElementById('distChart'), {
            type: 'bar',
            data: { labels: bins.map(b => b.label), datasets: [{ data: bins.map(b => b.count), backgroundColor: '#8b5cf6', borderRadius: 6 }] },
            options: { 
                ...commonOptions, 
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const b = bins[ctx.dataIndex];
                                return [`PnL Sum: ${b.pnl_sum > 0 ? '+' : ''}${b.pnl_sum.toFixed(2)}%`];
                            }
                        }
                    }
                },
                scales: { x: { ticks: { color: '#64748b' } }, y: { ticks: { color: '#64748b', stepSize: 1 } } } 
            }
        });
    </script>
</body></html>""".replace("{{SYMBOL}}", symbol).replace("{{JSON_DATA}}", json.dumps(dataset)).replace("{{GEN_TIME}}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        
        # 2. Physical Persistence
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        self.logger.info(f"Dashboard generated: {os.path.basename(output_path)}")

        # 3. Notification (Optional)
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

            norm = self._normalize_audit_report(data)
            if norm: extracted.append(norm)
            
        extracted.sort(key=lambda x: x['observation_time'] or "")
        return extracted

    def _normalize_audit_report(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parses a single JSON audit report and extracts normalized performance telemetry."""
        # v6.18: Unified Ledger Filtering (Including Neutral cases for full forensics)
        outcome = data.get("market_outcome", {})

        session = data.get("session", {})
        fd = session.get("final_decision", {})
        opinion = fd.get("opinion", "").upper()
        
        if opinion not in ["BULLISH", "BEARISH", "NEUTRAL"]: return None

        lo = fd.get("tactical_parameters", {})
        entry = float(lo.get("entry", 0))
        res = outcome.get("tp_sl_result", "NEITHER")
        pnl = 0.0
        if entry > 0:
            if res == "TP_HIT": 
                pnl = abs(float(lo.get("take_profit", 0)) - entry) / entry * 100
            elif res == "SL_HIT": 
                pnl = -abs(entry - float(lo.get("stop_loss", 0))) / entry * 100

        return {
            "observation_time": session.get("observation", {}).get("observed_at") or "",
            "is_filled": outcome.get("is_filled", False),
            "tp_sl_result": res,
            "estimated_pnl_pct": round(pnl, 2),
            "confidence": fd.get("confidence_score", 0),
            "holding_time_hours": lo.get("holding_time_hours", 0)
        }
