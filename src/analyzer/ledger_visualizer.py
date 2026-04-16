import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.utils.json_utils import load_json
from src.utils.path_utils import resolve_project_root
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
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-lg font-semibold text-slate-200">Decision Timeline</h2>
                <div class="flex items-center space-x-3 bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700">
                    <label class="text-xs font-medium text-slate-400 uppercase tracking-wider">Min Confidence:</label>
                    <input type="range" id="confSlider" min="40" max="100" value="40" class="w-32 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500">
                    <span id="confVal" class="text-sm font-mono text-emerald-400 w-8 text-center font-bold">40</span>
                </div>
            </div>
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
        const sortedTrades = [...RAW_DATA].sort((a, b) => new Date(a.observation_time.replace('Z', '')) - new Date(b.observation_time.replace('Z', '')));
        
        // --- Shared Scales & Options ---
        const scales = { 
            x: { 
                type: 'time', 
                time: { 
                    displayFormats: { 
                        hour: 'MMM dd HH:mm',
                        day: 'MMM dd',
                        month: 'MMM yyyy'
                    }
                }, 
                ticks: { color: '#64748b', maxRotation: 45, minRotation: 0, autoSkip: true }, 
                grid: { color: '#334155' },
                title: { display: true, text: 'Observation Time (UTC)', color: '#94a3b8', font: { size: 10 } }
            }, 
            y: { 
                ticks: { color: '#64748b' }, 
                grid: { color: '#334155' },
                title: { display: true, text: 'Confidence Score (%)', color: '#94a3b8', font: { size: 10 } }
            } 
        };
        const commonOptions = { 
            responsive: true, 
            maintainAspectRatio: false, 
            scales: scales, 
            plugins: { legend: { display: false } },
            animation: { duration: 400 }
        };

        // --- Data Preparation ---
        const bubbleDataOriginal = RAW_DATA.map(d => {
            let color = 'rgba(148, 163, 184, 0.1)'; 
            if (d.opinion !== 'NEUTRAL') {
                if (d.is_filled) {
                    if (d.tp_sl_result === 'TP_HIT') color = 'rgba(52, 211, 153, 0.9)';
                    else if (d.tp_sl_result === 'SL_HIT') color = 'rgba(251, 113, 133, 0.9)';
                    else if (d.estimated_pnl_pct > 0) color = 'rgba(52, 211, 153, 0.35)';
                    else if (d.estimated_pnl_pct < 0) color = 'rgba(251, 113, 133, 0.35)';
                    else color = 'rgba(100, 116, 139, 0.6)';
                } else {
                    color = 'rgba(148, 163, 184, 0.5)';
                }
            }
            return {
                x: d.observation_time ? new Date(d.observation_time.replace('Z', '')) : null, 
                y: d.confidence,
                r: Math.max(8, Math.min(25, Math.abs(d.estimated_pnl_pct) * 8 + (d.confidence / 10))),
                pnl: d.estimated_pnl_pct,
                res: d.tp_sl_result,
                op: d.opinion,
                filled: d.is_filled,
                holding: d.projected_holding_hours,
                timeLabel: d.observation_time ? new Date(d.observation_time).toLocaleString('en-GB', { timeZone: 'UTC', hour12: false }) + ' UTC' : 'Unknown',
                color: color
            };
        });

        // --- Chart Initialization ---
        const timelineChart = new Chart(document.getElementById('timelineChart'), { 
            type: 'bubble', 
            data: { datasets: [{ data: bubbleDataOriginal, backgroundColor: bubbleDataOriginal.map(d => d.color), borderColor: 'rgba(255, 255, 255, 0.2)', borderWidth: 1 }] }, 
            options: { 
                ...commonOptions, 
                plugins: { 
                    legend: { display: false },
                    tooltip: { 
                        callbacks: { 
                            label: (ctx) => {
                                const d = ctx.raw;
                                const status = d.op === 'NEUTRAL' ? 'Neutral' : d.filled ? d.res : 'Missed';
                                return [
                                    `Time: ${d.timeLabel}`,
                                    `Bias: ${d.op}`, 
                                    `Result: ${status}`, 
                                    `PnL: ${d.pnl > 0 ? '+' : ''}${d.pnl}%`, 
                                    `Holding: ${d.holding}h` 
                                ];
                            } 
                        } 
                    } 
                } 
            } 
        });

        const equityChart = new Chart(document.getElementById('equityChart'), { 
            type: 'line', 
            data: { datasets: [{ data: [], borderColor: '#a78bfa', borderWidth: 3, pointRadius: 4, pointBackgroundColor: '#a78bfa', fill: true, backgroundColor: 'rgba(167, 139, 250, 0.05)' }] }, 
            options: {
                ...commonOptions,
                scales: {
                    ...scales,
                    y: { ...scales.y, title: { display: true, text: 'Cumulative Equity (%)', color: '#94a3b8', font: { size: 10 } } }
                }
            } 
        });

        // --- Core Update Logic ---
        function updateDashboard(threshold) {
            // 1. Update Decision Timeline Visibility
            const filteredBubbles = bubbleDataOriginal.map(d => ({
                ...d,
                backgroundColor: d.y >= threshold ? d.color : 'rgba(0,0,0,0)',
                borderColor: d.y >= threshold ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0,0,0,0)'
            }));
            timelineChart.data.datasets[0].backgroundColor = filteredBubbles.map(d => d.backgroundColor);
            timelineChart.data.datasets[0].borderColor = filteredBubbles.map(d => d.borderColor);
            timelineChart.update('none');

            // 2. Metrics Calculation
            const activeTrades = sortedTrades.filter(d => d.confidence >= threshold);
            const executedTrades = activeTrades.filter(d => d.is_filled);
            
            let eq = 1.0, peak = 1.0, dd = 0;
            const curve = [];
            executedTrades.forEach(t => {
                eq *= (1 + t.estimated_pnl_pct / 100.0);
                if (eq > peak) peak = eq;
                dd = Math.max(dd, (peak - eq) / peak);
                curve.push({ x: new Date(t.observation_time.replace('Z', '')), y: (eq - 1) * 100 });
            });

            const netPnL = (eq - 1) * 100;
            const mddPct = dd * 100;
            const calmar = mddPct > 0 ? (netPnL / mddPct) : 0;

            // 3. Update DOM
            document.getElementById('kpi-executed').innerText = `${executedTrades.length} / ${activeTrades.length}`;
            document.getElementById('kpi-mdd').innerText = mddPct.toFixed(2) + '%';
            document.getElementById('kpi-pnl').innerText = netPnL.toFixed(2) + '%';
            document.getElementById('kpi-calmar').innerText = calmar.toFixed(2);
            document.getElementById('confVal').innerText = threshold;

            // 4. Update Equity Chart
            equityChart.data.datasets[0].data = curve;
            equityChart.update('none');
        }

        // --- Interactive Filter Logic ---
        document.getElementById('confSlider').addEventListener('input', (e) => {
            updateDashboard(parseInt(e.target.value));
        });

        // Initial Run
        updateDashboard(40);

        // --- Static Charts (Logic unchanged but moved down) ---
        const commonStaticOptions = { ...commonOptions, plugins: { legend: { display: false } } };
        
        // 3. Confidence Threshold Optimizer
        const optThresholds = [], optimizerData = [];
        const fullExecuted = sortedTrades.filter(d => d.is_filled);
        for (let t = 40; t <= 100; t += 5) {
            let pnlSum = 0;
            fullExecuted.forEach(trade => { if (trade.confidence >= t) pnlSum += trade.estimated_pnl_pct; });
            optThresholds.push(t);
            optimizerData.push(pnlSum);
        }
        new Chart(document.getElementById('optimizerChart'), {
            type: 'line',
            data: { labels: optThresholds, datasets: [{ data: optimizerData, borderColor: '#60a5fa', backgroundColor: 'rgba(96, 165, 250, 0.1)', borderWidth: 3, fill: true, tension: 0.3 }] },
            options: { ...commonOptions, scales: { x: { title: { display: true, text: 'Min Confidence Threshold (%)', color: '#94a3b8' }, ticks: { color: '#64748b' } }, y: { ticks: { color: '#64748b' }, grid: { color: '#334155' } } } }
        });

        // 4. Confidence Distribution
        const bins = [];
        for (let i = 40; i <= 95; i += 5) { bins.push({ label: `${i}-${i+4}`, min: i, max: i + 5, count: 0, pnl_sum: 0 }); }
        fullExecuted.forEach(s => { 
            const conf = parseFloat(s.confidence);
            bins.forEach(b => { if (conf >= b.min && conf < b.max) { b.count++; b.pnl_sum += s.estimated_pnl_pct; } }); 
        });
        new Chart(document.getElementById('distChart'), {
            type: 'bar',
            data: { labels: bins.map(b => b.label), datasets: [{ data: bins.map(b => b.count), backgroundColor: '#8b5cf6', borderRadius: 6 }] },
            options: { ...commonOptions, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => { const b = bins[ctx.dataIndex]; return [`PnL Sum: ${b.pnl_sum > 0 ? '+' : ''}${b.pnl_sum.toFixed(2)}%`]; } } } }, scales: { x: { ticks: { color: '#64748b' } }, y: { ticks: { color: '#64748b', stepSize: 1 } } } }
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
        res = outcome.get("tp_sl_result", "NEITHER")
        entry_price = float(lo.get("entry") or 0)
        pnl = 0.0
        
        # v6.25: Holistic PnL Calculation (TP, SL, or Time-based Exit)
        if outcome.get("is_filled", False) and entry_price > 0:
            forensics = outcome.get("market_forensics", {})
            # Use market exit price if available, fallback to TP/SL logic if needed
            exit_price = forensics.get("price_at_t1") or entry_price
            
            if res == "TP_HIT":
                # Static distance for TP (always positive edge)
                tp_price = float(lo.get("take_profit") or entry_price)
                pnl = abs(tp_price - entry_price) / entry_price * 100
            elif res == "SL_HIT":
                # Static distance for SL (always negative edge)
                sl_price = float(lo.get("stop_loss") or entry_price)
                pnl = -abs(entry_price - sl_price) / entry_price * 100
            else:
                # NEITHER case: Directional delta from entry to exit (Price at T1)
                price_delta = exit_price - entry_price
                if opinion == "BULLISH":
                    pnl = (price_delta / entry_price) * 100
                elif opinion == "BEARISH":
                    pnl = (-price_delta / entry_price) * 100

        return {
            "observation_time": session.get("observation", {}).get("observed_at") or "",
            "opinion": opinion,
            "is_filled": outcome.get("is_filled", False),
            "tp_sl_result": res,
            "estimated_pnl_pct": round(pnl, 2),
            "confidence": fd.get("confidence_score", 0),
            "projected_holding_hours": lo.get("projected_holding_hours") or 0
        }
