# Log Parsing Utilities

Reusable Python parser for sniper.log SIGNAL DIAG and WAKE lines.
Use these in inline Python blocks when analyzing logs.

⚠️ **Timezone**: Log timestamps are in the **machine's local timezone**.
Session filenames and `observed_at` are **UTC**. Always convert:

```python
from datetime import datetime, timezone, timedelta
LOCAL_TZ = timezone(timedelta(hours=12))  # Adjust: run `date +%Z` first

# Parse log timestamps as local:
ts = datetime.strptime(f"{date_str} {hhmmss}", "%Y-%m-%d %H:%M:%S.%f")
ts = ts.replace(tzinfo=LOCAL_TZ)

# Parse session observed_at as UTC:
sess_ts = datetime.fromisoformat(obs_ts.replace('Z', '+00:00'))
local_ts = sess_ts.astimezone(LOCAL_TZ)  # Convert for comparison
```

## SIGNAL DIAG Parser

Parses both fired (`F:0.XX`) and rejected (`R:reason`) detectors.
Also extracts the raw metrics (cvd, vii, vpr, etc.) and the rejection
reason text for threshold gap analysis.

```python
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# Adjust to your machine's timezone
LOCAL_TZ = timezone(timedelta(hours=12))

def parse_signal_diag(line: str, date_str: str) -> dict | None:
    """Parse one SIGNAL DIAG line. Returns dict or None if not a DIAG line."""
    if 'SIGNAL DIAG' not in line or '[trigger' not in line:
        return None

    ts_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
    if not ts_match:
        return None
    ts = datetime.strptime(f"{date_str} {ts_match.group(1)}",
                           "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=LOCAL_TZ)
    ts = datetime.strptime(f"{date_str} {ts_match.group(1)}",
                           "%Y-%m-%d %H:%M:%S.%f")

    # Extract symbol
    sym_match = re.search(r'\[(\w+)\] SIGNAL DIAG', line)
    symbol = sym_match.group(1) if sym_match else 'UNKNOWN'

    # Split by " | " to get fields — avoids the R:reason containing | issue
    body = line.split('SIGNAL DIAG | ', 1)[-1]
    fields = body.split(' | ')
    detectors = {}
    for field in fields:
        field = field.strip()
        m = re.match(r'(\w+)=(F:[\d.]+|R:.+)', field)
        if not m:
            continue
        name = m.group(1)
        value = m.group(2)
        # Skip metric-only fields (not detectors)
        if name in ('cvd', 'vii', 'vpr', 'price', 'atr', 'ls', 'fund', 'oi_d', 'trade_sz', 'sf'):
            continue
        if value.startswith('F:'):
            strength_str = value[2:]
            sm = re.match(r'([\d.]+)', strength_str)
            detectors[name] = {'status': 'FIRED', 'strength': float(sm.group(1)) if sm else 0.0}
        else:
            detectors[name] = {'status': 'REJECTED', 'reason': value[2:].strip()}

    # Parse numeric metrics
    def _get(pattern, line, cast=float, default=None):
        m = re.search(pattern, line)
        return cast(m.group(1)) if m else default

    return {
        'timestamp': ts,
        'symbol': symbol,
        'metrics': {
            'cvd': _get(r'cvd=(-?[\d.]+)', line),
            'vii': _get(r'vii=(-?[\d.]+)', line),
            'vpr': _get(r'vpr=(-?[\d.]+)', line),
            'sf': _get(r'sf=(-?[\d.]+)', line),
            'price': _get(r'price=(-?[\d.]+)', line),
            'atr': _get(r'atr=(-?[\d.]+)', line),
            'ls_ratio': _get(r'ls=(-?[\d.]+)', line),
            'funding': _get(r'fund=(-?[\d.]+)', line),
            'oi_delta': _get(r'oi_d=(-?[\d.]+)', line),
            'avg_trade_size': _get(r'trade_sz=(-?[\d.]+)', line),
        },
        'detectors': detectors,
    }

def parse_trigger_wake(line: str, date_str: str) -> dict | None:
    """Parse [trigger] WAKE lines only (not SniperDaemon WAKE UP)."""
    if 'WAKE' not in line or '[trigger' not in line:
        return None
    if 'WAKE UP' in line or '🔫' in line:
        return None

    ts_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
    if not ts_match:
        return None
    ts = datetime.strptime(f"{date_str} {ts_match.group(1)}",
                           "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=LOCAL_TZ)

    sym_match = re.search(r'\[(\w+)\] WAKE', line)
    symbol = sym_match.group(1) if sym_match else 'UNKNOWN'
    dir_match = re.search(r'dir=(\w+)', line)
    direction = dir_match.group(1) if dir_match else '?'
    conf_match = re.search(r'confluence=([\d.]+)', line)
    confluence = float(conf_match.group(1)) if conf_match else 0.0
    fresh_match = re.search(r'fresh=(\d+)', line)
    fresh = int(fresh_match.group(1)) if fresh_match else 0
    memory_match = re.search(r'memory=(\d+)', line)
    memory = int(memory_match.group(1)) if memory_match else 0
    active_match = re.search(r"active=\[([^\]]*)\]", line)
    active_signals = []
    if active_match and active_match.group(1).strip():
        active_signals = [s.strip().strip("'") for s in active_match.group(1).split(',')]
    gate_match = re.search(r'gate=(\w+)', line)
    gate = gate_match.group(1) if gate_match else '?'
    regime_match = re.search(r'regime=(\w+)', line)
    regime = regime_match.group(1) if regime_match else '?'

    return {
        'timestamp': ts, 'symbol': symbol, 'direction': direction,
        'confluence': confluence, 'fresh_signals': fresh, 'memory_signals': memory,
        'active_signals': active_signals, 'gate': gate, 'regime': regime,
    }
```

## Rejection Reason Collector

```python
def collect_rejection_reasons(records: list[dict]) -> dict:
    """Collect unique rejection reasons per signal, with counts.
    Returns {(symbol, signal): Counter(reason_text: count)}."""
    from collections import Counter
    reasons = defaultdict(lambda: Counter())
    for r in records:
        sym = r['symbol']
        for sig_name, det in r['detectors'].items():
            if det['status'] == 'REJECTED':
                reasons[(sym, sig_name)][det['reason']] += 1
    return dict(reasons)
```

## Aggregate Analysis

```python
def aggregate_signals(records: list[dict]) -> dict:
    """Given parsed SIGNAL DIAG records, compute per-signal per-symbol stats."""
    # records = list of parse_signal_diag() results
    stats = defaultdict(lambda: defaultdict(lambda: {
        'fired': 0, 'rejected': 0, 'strengths': [], 'symbol': ''
    }))

    for r in records:
        sym = r['symbol']
        for sig_name, det in r['detectors'].items():
            key = (sym, sig_name)
            s = stats[key]
            s['symbol'] = sym
            if det['status'] == 'FIRED':
                s['fired'] += 1
                s['strengths'].append(det['strength'])
            else:
                s['rejected'] += 1

    result = {}
    for (sym, sig_name), s in stats.items():
        total = s['fired'] + s['rejected']
        strengths = s['strengths']
        result[(sym, sig_name)] = {
            'symbol': sym,
            'signal': sig_name,
            'fired': s['fired'],
            'rejected': s['rejected'],
            'fire_rate': s['fired'] / total if total > 0 else 0,
            'avg_strength': sum(strengths) / len(strengths) if strengths else 0,
            'max_strength': max(strengths) if strengths else 0,
            'min_strength': min(strengths) if strengths else 0,
        }
    return result

def aggregate_wakes(wakes: list[dict]) -> dict:
    """Given parsed WAKE records, compute per-symbol wake stats."""
    stats = defaultdict(lambda: {
        'total': 0, 'bullish': 0, 'bearish': 0,
        'confluences': [], 'signal_counts': [],
        'gate_fails': 0, 'regimes': [],
        'timestamps': [],
    })

    for w in wakes:
        s = stats[w['symbol']]
        s['total'] += 1
        if w['direction'] == 'BULLISH':
            s['bullish'] += 1
        else:
            s['bearish'] += 1
        s['confluences'].append(w['confluence'])
        s['signal_counts'].append(w['fresh_signals'] + w['memory_signals'])
        if w['gate'] == 'FAIL':
            s['gate_fails'] += 1
        s['regimes'].append(w['regime'])
        s['timestamps'].append(w['timestamp'])

    result = {}
    for sym, s in stats.items():
        intervals = []
        times = sorted(s['timestamps'])
        for i in range(1, len(times)):
            gap = (times[i] - times[i-1]).total_seconds() / 60
            intervals.append(gap)

        from statistics import mean, median
        result[sym] = {
            'symbol': sym,
            'wakes': s['total'],
            'bullish': s['bullish'],
            'bearish': s['bearish'],
            'avg_confluence': mean(s['confluences']) if s['confluences'] else 0,
            'avg_signals': mean(s['signal_counts']) if s['signal_counts'] else 0,
            'gate_fail_rate': s['gate_fails'] / s['total'] if s['total'] > 0 else 0,
            'dominant_regime': max(set(s['regimes']), key=s['regimes'].count) if s['regimes'] else 'unknown',
            'min_interval': min(intervals) if intervals else None,
            'avg_interval': mean(intervals) if intervals else None,
            'median_interval': median(intervals) if intervals else None,
        }
    return result
```

## Usage Example

```python
# Read log for a date range
from datetime import datetime

date_str = "2026-07-06"
records = []
wakes = []

with open("data/prod/sniper.log") as f:
    for line in f:
        diag = parse_signal_diag(line, date_str)
        if diag:
            records.append(diag)
            continue
        wake = parse_wake(line, date_str)
        if wake:
            wakes.append(wake)

# Aggregate
signal_stats = aggregate_signals(records)
wake_stats = aggregate_wakes(wakes)

# Print signal health table
print("| Signal | Symbol | Fired | Rejected | Rate | Avg Str | Max Str |")
print("|--------|--------|-------|----------|------|---------|---------|")
for (sym, sig), s in sorted(signal_stats.items()):
    print(f"| {sig} | {sym} | {s['fired']} | {s['rejected']} | "
          f"{s['fire_rate']:.1%} | {s['avg_strength']:.2f} | {s['max_strength']:.2f} |")
```
