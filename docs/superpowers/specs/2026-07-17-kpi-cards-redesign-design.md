# KPI Cards Redesign — Design Spec

**Date:** 2026-07-17
**Status:** Draft

## Overview

Redesign the Performance dashboard page (`/performance`) to replace the current flat KPI stat boxes with enriched cards containing dual-line sparklines, and strip PnL-related data from the Decision Timeline bubble chart.

---

## 1. KPI Cards — New Structure

### 1.1 Layout

7 cards, all same width and height, arranged in responsive CSS grid:

```
┌──────────────────────────────────────────────────────┐
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │ NET P&L  │ │ WIN RATE │ │W/L RATIO │ │FILL RATE ││
│  │  +0.90%  │ │   50%    │ │   1.24   │ │   94%    ││
│  │ ══spark══│ │ ══spark══│ │ ══spark══│ │ ══spark══││
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘│
│  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │MFE EFF.  │ │MAE STRESS│ │MAX DRAWDN│              │
│  │   72%    │ │   38%    │ │  -1.93%  │              │
│  │ ══spark══│ │ ══spark══│ │ ══spark══│              │
│  └──────────┘ └──────────┘ └──────────┘              │
└──────────────────────────────────────────────────────┘
```

- Grid: `grid-template-columns: repeat(auto-fill, minmax(180px, 1fr))`
- 7 cards means typical layout: 4 on first row, 3 on second row
- Gap: 12px between cards

### 1.2 Card Anatomy

Each card contains, top to bottom:

```
┌──────────────────────────┐
│  NET P&L        +0.90%  │  ← name (left) + all-trades ref (right, dim)
│                          │
│  +12.40%                 │  ← filtered value (large, colored)
│                          │
│  ════════════════════════│  ← dual-line sparkline (44px tall)
│  ────────────────────────│     gray = all-trades baseline
│                          │     colored = filtered by confidence
└──────────────────────────┘
        ↑ left-border: 3px, health-colored
```

**Visual specs:**
| Element | Value |
|----------|-------|
| Card background | `var(--bg-card)` (#1d2a39) |
| Card border | 1px `var(--border-muted)` (#1f2d3d), radius 8px |
| Left border accent | 3px, colored by KPI health (green/amber/red) |
| Card padding | 12px 14px 10px 14px |
| KPI name | 10px, uppercase, `var(--text-muted)` (#6e7d91), weight 600, letter-spacing 0.06em |
| All-trades reference | 11px, mono, `var(--text-muted)` (#6e7d91), positioned top-right |
| Filtered value | 22px, weight 700, mono, health-colored |
| Sparkline area | 44px height, SVG, margin-top 6px |
| Gray line (all trades) | `rgba(136, 152, 172, 0.3)`, stroke-width 1.2 |
| Colored line (filtered) | KPI's accent color at full opacity, stroke-width 2 |
| Sparkline x-axis | Session index (no time labels) |
| Sparkline y-axis | No visible axis — sparkline is for trend direction only |

### 1.3 KPI Color Assignments

| KPI | Accent Color |
|-----|-------------|
| NET P&L | `--accent-green` (#40a85f) |
| WIN RATE | `--accent-gold` (#d4a348) |
| WIN / LOSS | `--accent-teal` (#54a0a8) |
| FILL RATE | `--accent-purple` (#9488d8) |
| MFE EFFICIENCY | `--accent-blue` (#4a8fe0) |
| MAE STRESS | `--accent-amber` (#c9953a) |
| MAX DRAWDOWN | `--accent-red` (#e0554a) |

Left-border health coloring (green/amber/red) still applies based on the same thresholds used today. The value text uses the KPI's accent color (above), not health color.

### 1.4 All-Trades Reference Value

- Each card shows the KPI computed over ALL trades (ignoring confidence threshold) as a small dim number
- Position: top-right corner of card, aligned with KPI name
- Format: same unit as the main value (e.g., `+8.10%`, `55%`, `1.85`)
- This value does NOT change when the slider moves — it's a fixed baseline

### 1.5 Dual-Line Sparkline Data

The x-axis is session index (1, 2, 3...), not timestamps.

Data for each sparkline:
- **Gray line**: KPI value computed cumulatively over all trades, regardless of confidence. Precomputed and static.
- **Colored line**: KPI value computed cumulatively over only trades with confidence ≥ threshold. Recomputed on slider change.

Data is computed as a rolling cumulative: for each session index N, the KPI is computed over trades 1..N. This produces a line that shows the KPI's evolution as more trades are added.

---

## 2. Decision Timeline — PnL Removal

### 2.1 What Stays (unchanged)

- Bubble scatter chart: X = time, Y = confidence
- Bubble color: green (TP), red (SL), gray (neutral/unfilled)
- Bubble transparency: below-threshold points dimmed/hidden
- Confidence threshold line (dashed gold, with label "≥ 55%")
- Confidence slider control
- Chart.js tooltip (with symbol, time, opinion, confidence, holding, version)
- Click-to-navigate (click bubble → session detail)
- Threshold slider filtering

### 2.2 What Is Removed

1. **Bubble radius PnL encoding** — `r` formula uses `Math.abs(t.pnl_pct)` currently. Replace with uniform radius (e.g., fixed 8px for all bubbles).

2. **Equity curve line** — the second dataset (`type: 'line'`, `yAxisID: 'y2'`) that shows cumulative PnL as a line overlaid on the bubble chart. REMOVE entirely.

3. **Right-side Y-axis (y2)** — the secondary axis showing PnL percentage labels (`+2.5%`, `-1.3%`, etc.). REMOVE entirely.

4. **Equity curve data** — the `curve` array passed to `renderTimeline`. No longer needed.

5. **Tooltip PnL string** — remove `pnl: t.pnl_pct` from the point data object and remove the PnL line from the tooltip callback.

### 2.3 Data Flow (Unchanged)

The confidence slider triggers `updateAllCharts(threshold)` which:
1. Filters trades by threshold
2. Recomputes KPI values
3. Calls `renderTimeline(trades, threshold, curve)` — `curve` param becomes `[]` (empty)

---

## 3. Confidence Slider Behavior

- Slider stays in the chart controls area (same position as now)
- On change → debounced callback → `updateAllCharts(threshold)`
- `updateAllCharts` updates:
  - All 7 KPI cards: filtered value text + colored sparkline redraw
  - Bubble chart: re-rendered with filtered visibility
  - Trade ledger: filtered rows

None of the 7 cards' gray lines or all-trades reference values change on slider move.

---

## 4. Files to Modify

| File | Changes |
|------|---------|
| `src/dashboard/templates/index.html` | Restructure KPI section HTML; update `renderTimeline` (remove PnL); update `updateAllCharts`; add sparkline rendering functions |
| `src/dashboard/static/dashboard.css` | Replace `.kpi-grid` / `.kpi-card` / `.kpi-label` / `.kpi-value` styles with new card styles; add sparkline container styles |
| `src/dashboard/static/i18n.js` | Verify KPI labels match new names (minor — may need key additions for full names) |

No changes needed to:
- `src/dashboard/api/` — endpoints unchanged
- `src/dashboard/server.py` — server unchanged
- `src/dashboard/static/dashboard-utils.js` — utility functions unchanged

---

## 5. Implementation Notes

- Sparklines use inline SVG (no library) — simple `<svg>` with `<polyline>` elements
- Sparkline data arrays are precomputed in `updateAllCharts`:
  - For each session (sorted by time), compute cumulative KPI over trades 1..N
  - Produce two arrays: `allLine` (all trades) and `filteredLine` (confidence ≥ threshold)
  - Map to SVG polyline points
- The `r` (bubble radius) change is a one-line fix: replace `Math.max(6, Math.min(22, Math.abs(t.pnl_pct) * 6 + t.confidence / 10))` with a constant (e.g., `8`)
- The equity curve removal is deleting the second dataset object and the `y2` scale config
- Card health thresholds (green/amber/red) reuse existing logic from `_setKpiHealth`
- All-trades reference values must be computed once at load time, independent of threshold

---

## 6. States

### Loading State
All values show `--`, sparklines empty (single flat line or hidden).

### Empty State (no trades)
All cards show `—` for values, sparklines hidden.

### Single Trade
Sparklines show a single point (short horizontal line), values computed normally.

### Error State
API errors show existing error handling (unchanged).
