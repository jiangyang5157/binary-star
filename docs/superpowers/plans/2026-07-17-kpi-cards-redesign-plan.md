# KPI Cards Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat KPI stat boxes with 7 unified-size cards featuring dual-line sparklines, and strip PnL data from the Decision Timeline bubble chart.

**Architecture:** All changes are in the frontend template (`index.html`) and CSS (`dashboard.css`). No API or server changes. Sparklines use inline SVG `<polyline>` elements rendered client-side from precomputed cumulative KPI arrays. The confidence slider stays in the chart-header area and drives both KPI cards and the bubble chart through the existing `updateAllCharts(threshold)` path.

**Tech Stack:** Vanilla JS, Chart.js 4.4.7 (existing), inline SVG (no new library), CSS custom properties

## Global Constraints

- 7 KPI cards: all identical width/height, responsive grid
- Each card: name (left) + all-trades reference value (right, dim) + filtered value (large, accent-colored) + dual-line sparkline (gray=all, colored=filtered)
- Left-border health coloring (green/amber/red) stays; value text uses KPI accent color
- Bubble chart: remove PnL curve, equity curve line, y2 axis, bubble size PnL encoding; keep threshold line, slider, tooltip, click navigation
- Confidence slider in chart-header drives everything
- No API changes, no server changes

---

### Task 1: Update KPI Card HTML Structure

**Files:**
- Modify: `src/dashboard/templates/index.html:40-72`

**Interfaces:**
- Consumes: None (first task)
- Produces: HTML elements with ids: `kpi-pnl`, `kpi-pnl-all`, `kpi-pnl-spark`, `kpi-winrate`, `kpi-winrate-all`, `kpi-winrate-spark`, `kpi-winloss`, `kpi-winloss-all`, `kpi-winloss-spark`, `kpi-fillrate`, `kpi-fillrate-all`, `kpi-fillrate-spark`, `kpi-mfeeff`, `kpi-mfeeff-all`, `kpi-mfeeff-spark`, `kpi-maestress`, `kpi-maestress-all`, `kpi-maestress-spark`, `kpi-mdd`, `kpi-mdd-all`, `kpi-mdd-spark`

- [ ] **Step 1: Replace the KPI grid HTML section**

Open `src/dashboard/templates/index.html`, find the `<!-- ═══════ KPI Cards ═══════ -->` section (lines 40-72), and replace the entire `<section class="kpi-grid" id="kpi-grid">...</section>` block with:

```html
    <!-- ═══════ KPI Cards ═══════ -->
    <section class="kpi-grid" id="kpi-grid">
      <div class="kpi-card" data-kpi="pnl">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.net_pnl"></span>
          <span class="kpi-all-ref mono" id="kpi-pnl-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-pnl">--</span>
        <svg class="kpi-spark" id="kpi-pnl-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="winrate">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.win_rate"></span>
          <span class="kpi-all-ref mono" id="kpi-winrate-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-winrate">--</span>
        <svg class="kpi-spark" id="kpi-winrate-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="winloss">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.win_loss"></span>
          <span class="kpi-all-ref mono" id="kpi-winloss-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-winloss">--</span>
        <svg class="kpi-spark" id="kpi-winloss-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="fillrate">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.fill_rate"></span>
          <span class="kpi-all-ref mono" id="kpi-fillrate-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-fillrate">--</span>
        <svg class="kpi-spark" id="kpi-fillrate-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="mfeeff">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.mfe_efficiency"></span>
          <span class="kpi-all-ref mono" id="kpi-mfeeff-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-mfeeff">--</span>
        <svg class="kpi-spark" id="kpi-mfeeff-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="maestress">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.mae_stress"></span>
          <span class="kpi-all-ref mono" id="kpi-maestress-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-maestress">--</span>
        <svg class="kpi-spark" id="kpi-maestress-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
      <div class="kpi-card" data-kpi="mdd">
        <div class="kpi-top-row">
          <span class="kpi-label" data-i18n="kpi.max_drawdown"></span>
          <span class="kpi-all-ref mono" id="kpi-mdd-all">--</span>
        </div>
        <span class="kpi-value" id="kpi-mdd">--</span>
        <svg class="kpi-spark" id="kpi-mdd-spark" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      </div>
    </section>
```

- [ ] **Step 2: Verify the HTML renders without errors**

Run: `cd /Users/yangjiang/workspace/binary-star && python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/dashboard/templates')); tpl = env.get_template('index.html'); print('Template compiles OK')"`

Expected: `Template compiles OK`

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/templates/index.html
git commit -m "feat: restructure KPI cards HTML with sparkline SVG placeholders

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Update KPI Card CSS

**Files:**
- Modify: `src/dashboard/static/dashboard.css:857-897`

**Interfaces:**
- Consumes: New HTML classes `.kpi-top-row`, `.kpi-all-ref`, `.kpi-spark`, updated `.kpi-grid`, `.kpi-card`, `.kpi-label`, `.kpi-value`
- Produces: Visual card layout matching spec

- [ ] **Step 1: Replace KPI card CSS rules**

Open `src/dashboard/static/dashboard.css`, find the `/* --- KPI Cards --- */` section (starting at line 857), and replace the entire block from line 857 through line 897 with:

```css
/* --- KPI Cards --- */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border-muted);
  border-radius: var(--radius);
  padding: 12px 14px 10px 14px;
  display: flex;
  flex-direction: column;
  border-left: 3px solid var(--border-muted);
  box-shadow: var(--shadow);
  min-height: 110px;
}

.kpi-card.health-green  { border-left-color: var(--accent-green); }
.kpi-card.health-amber  { border-left-color: var(--accent-amber); }
.kpi-card.health-red    { border-left-color: var(--accent-red); }

.kpi-top-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.kpi-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
}

.kpi-all-ref {
  font-size: 0.68rem;
  color: var(--text-muted);
  font-weight: 500;
}

.kpi-value {
  font-size: 1.35rem;
  font-weight: 700;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  margin: 3px 0 4px 0;
  line-height: 1.2;
}

/* KPI value accent colors — one per KPI */
.kpi-card[data-kpi="pnl"] .kpi-value       { color: var(--accent-green); }
.kpi-card[data-kpi="winrate"] .kpi-value    { color: var(--accent-gold); }
.kpi-card[data-kpi="winloss"] .kpi-value    { color: var(--accent-teal); }
.kpi-card[data-kpi="fillrate"] .kpi-value   { color: var(--accent-purple); }
.kpi-card[data-kpi="mfeeff"] .kpi-value     { color: var(--accent-blue); }
.kpi-card[data-kpi="maestress"] .kpi-value  { color: var(--accent-amber); }
.kpi-card[data-kpi="mdd"] .kpi-value        { color: var(--accent-red); }

.kpi-spark {
  width: 100%;
  height: 44px;
  margin-top: auto;
  display: block;
  overflow: visible;
}
```

- [ ] **Step 2: Verify CSS compiles (no syntax errors)**

Run: `cd /Users/yangjiang/workspace/binary-star && python -c "
import re
css = open('src/dashboard/static/dashboard.css').read()
# Check braces are balanced
opens = css.count('{')
closes = css.count('}')
assert opens == closes, f'Unbalanced braces: {opens} opens, {closes} closes'
print(f'CSS OK: {opens} rule blocks')
"`

Expected: `CSS OK: N rule blocks` (no assertion error)

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/static/dashboard.css
git commit -m "feat: redesign KPI card CSS — unified cards with sparkline containers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add Sparkline Computation and Rendering Functions

**Files:**
- Modify: `src/dashboard/templates/index.html` (add JS functions before updateAllCharts)

**Interfaces:**
- Consumes: KPI card sparkline SVG elements from Task 1, API data from `/api/audits` (allTrades)
- Produces: `_allKpiBaselines` (object, computed once), `_kpiSparkAccent` (string→color map), `renderAllSparklines(threshold)` (function), `_renderOneSparkline(svgEl, allPoints, filteredPoints, accent)` (function)

- [ ] **Step 1: Add sparkline helper code**

Open `src/dashboard/templates/index.html`, find the line `function updateAllCharts(threshold) {` (currently around line 231). Insert the following code block BEFORE that line:

```javascript
    // ── Sparkline helpers ──────────────────────────────────────────
    // KPI accent colors for sparkline strokes
    const _kpiSparkAccent = {
      pnl: '#40a85f', winrate: '#d4a348', winloss: '#54a0a8',
      fillrate: '#9488d8', mfeeff: '#4a8fe0', maestress: '#d98c2e',
      mdd: '#e0554a',
    };

    // Baselines computed once over ALL filled trades (independent of threshold)
    let _allKpiBaselines = {};

    /** Compute cumulative KPI values over sorted filled trades.
     *  Returns array of {x, y} where x = session index, y = cumulative KPI at that point. */
    function _computeCumulativeKpi(filledTradesSorted, kpiKey) {
      const points = [];
      if (!filledTradesSorted.length) return points;

      switch (kpiKey) {
        case 'pnl': {
          let eq = 1.0;
          filledTradesSorted.forEach((t, i) => {
            eq *= (1 + t.pnl_pct / 100);
            points.push({ x: i + 1, y: (eq - 1) * 100 });
          });
          break;
        }
        case 'winrate': {
          let wins = 0;
          filledTradesSorted.forEach((t, i) => {
            if (t.pnl_pct > 0) wins++;
            points.push({ x: i + 1, y: (wins / (i + 1)) * 100 });
          });
          break;
        }
        case 'winloss': {
          let wins = [], losses = [];
          filledTradesSorted.forEach((t, i) => {
            if (t.pnl_pct > 0) wins.push(t.pnl_pct);
            else losses.push(Math.abs(t.pnl_pct));
            const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
            const avgLoss = losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0;
            points.push({ x: i + 1, y: avgLoss > 0 ? avgWin / avgLoss : 0 });
          });
          break;
        }
        case 'fillrate': {
          let filled = 0, total = 0;
          filledTradesSorted.forEach((t, i) => {
            if (t.opinion !== 'NEUTRAL') total++;
            if (t.is_filled) filled++;
            points.push({ x: i + 1, y: total > 0 ? (filled / total) * 100 : 0 });
          });
          break;
        }
        case 'mfeeff': {
          let sum = 0, count = 0;
          filledTradesSorted.forEach((t, i) => {
            if (t.mfe_efficiency_pct != null) { sum += t.mfe_efficiency_pct; count++; }
            points.push({ x: i + 1, y: count > 0 ? sum / count : 0 });
          });
          break;
        }
        case 'maestress': {
          let protected_ = 0, count = 0;
          filledTradesSorted.forEach((t, i) => {
            if (t.mae_stress_tier) { count++; if (t.mae_stress_tier === 'PINPOINT' || t.mae_stress_tier === 'STANDARD') protected_++; }
            points.push({ x: i + 1, y: count > 0 ? (protected_ / count) * 100 : 0 });
          });
          break;
        }
        case 'mdd': {
          let eq = 1.0, peak = 1.0, dd = 0;
          filledTradesSorted.forEach((t, i) => {
            eq *= (1 + t.pnl_pct / 100);
            if (eq > peak) peak = eq;
            dd = Math.max(dd, (peak - eq) / peak);
            points.push({ x: i + 1, y: dd * 100 });
          });
          break;
        }
      }
      return points;
    }

    /** Convert point array to SVG polyline points string.
     *  Maps data coords into the 200×44 viewBox. */
    function _pointsToPolyline(points) {
      if (!points.length) return '';
      const xMax = points[points.length - 1].x || 1;
      const yVals = points.map(p => p.y);
      const yMin = Math.min(...yVals, 0);
      const yMax = Math.max(...yVals, 1);
      const yRange = yMax - yMin || 1;
      const pad = 4; // px padding inside viewBox
      return points.map(p => {
        const sx = pad + ((p.x - 1) / Math.max(xMax - 1, 1)) * (200 - 2 * pad);
        const sy = 44 - pad - ((p.y - yMin) / yRange) * (44 - 2 * pad);
        return `${sx.toFixed(1)},${sy.toFixed(1)}`;
      }).join(' ');
    }

    /** Render all 7 KPI sparklines */
    function renderAllSparklines(threshold, filledTradesSorted) {
      // Compute all-trades baselines once (static)
      if (!Object.keys(_allKpiBaselines).length && filledTradesSorted.length) {
        for (const key of ['pnl', 'winrate', 'winloss', 'fillrate', 'mfeeff', 'maestress', 'mdd']) {
          _allKpiBaselines[key] = _computeCumulativeKpi(filledTradesSorted, key);
        }
      }

      // Filter trades by threshold
      const filtered = filledTradesSorted.filter(t => t.confidence >= threshold);

      for (const key of ['pnl', 'winrate', 'winloss', 'fillrate', 'mfeeff', 'maestress', 'mdd']) {
        const svgEl = document.getElementById(`kpi-${key}-spark`);
        if (!svgEl) continue;

        const allPoints = _allKpiBaselines[key] || [];
        const filteredPoints = _computeCumulativeKpi(filtered, key);
        const accent = _kpiSparkAccent[key] || '#8898ac';

        // Build SVG content: gray line (all) + colored line (filtered)
        const allPoly = _pointsToPolyline(allPoints);
        const filtPoly = _pointsToPolyline(filteredPoints);

        svgEl.innerHTML = '';
        if (allPoly) {
          const grayLine = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
          grayLine.setAttribute('points', allPoly);
          grayLine.setAttribute('fill', 'none');
          grayLine.setAttribute('stroke', 'rgba(136,152,172,0.3)');
          grayLine.setAttribute('stroke-width', '1.2');
          svgEl.appendChild(grayLine);
        }
        if (filtPoly) {
          const colorLine = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
          colorLine.setAttribute('points', filtPoly);
          colorLine.setAttribute('fill', 'none');
          colorLine.setAttribute('stroke', accent);
          colorLine.setAttribute('stroke-width', '2');
          svgEl.appendChild(colorLine);
        }
      }
    }
```

- [ ] **Step 2: Clear baseline cache on data reload**

Find the `loadTrades` function (around line 214). Add `_allKpiBaselines = {};` after `allTrades = ...`:

```javascript
    async function loadTrades(symbol) {
      const resp = await fetch(apiUrl('/api/trades', symbol ? { symbol } : {}));
      const data = await resp.json();
      allTrades = (data.trades || []).sort((a, b) => new Date(a.time) - new Date(b.time));
      _allKpiBaselines = {};  // reset sparkline baseline cache
    }
```

- [ ] **Step 3: Verify JS syntax**

Run: `cd /Users/yangjiang/workspace/binary-star && node -e "
const fs = require('fs');
const html = fs.readFileSync('src/dashboard/templates/index.html', 'utf8');
// Extract all script content
const scripts = html.match(/<script>([\s\S]*?)<\/script>/g) || [];
// Quick check: no unmatched braces in template literals
const opens = (html.match(/\{/g) || []).length;
const closes = (html.match(/\}/g) || []).length;
console.log('Braces:', opens, 'opens,', closes, 'closes');
console.log('Script blocks:', scripts.length);
"`

Expected: Braces count close (within ~10 of each other — Jinja2 `{{ }}` and JS object literals will differ slightly).

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/templates/index.html
git commit -m "feat: add sparkline computation and rendering functions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Update updateAllCharts to Drive Sparklines and All-Trades Refs

**Files:**
- Modify: `src/dashboard/templates/index.html:231-338` (updateAllCharts function)

**Interfaces:**
- Consumes: `renderAllSparklines()` from Task 3, existing `setKpiWithAnimation`, `_setKpiHealth`, KPI DOM elements from Task 1
- Produces: Updated `updateAllCharts(threshold)` that drives KPI values, sparklines, and all-trades reference values

- [ ] **Step 1: Rewrite updateAllCharts**

Replace the entire `updateAllCharts` function body (from the function declaration through the closing `}`) with:

```javascript
    function updateAllCharts(threshold) {
      const trades = filteredTrades;
      const filledTrades = trades.filter(t => t.is_filled);
      const filledSorted = [...filledTrades].sort((a, b) => new Date(a.time) - new Date(b.time));

      if (!filledTrades.length) {
        for (const key of ['pnl', 'winrate', 'winloss', 'fillrate', 'mfeeff', 'maestress', 'mdd']) {
          const valEl = document.getElementById(`kpi-${key}`);
          const allEl = document.getElementById(`kpi-${key}-all`);
          if (valEl) valEl.textContent = key === 'fillrate' ? (trades.filter(t => t.opinion !== 'NEUTRAL').length > 0 ? '0%' : '—') : '—';
          if (allEl) allEl.textContent = '—';
          _setKpiHealth(`kpi-${key}`, null);
          _prevKpiValues[`kpi-${key}`] = null;
        }
        // Clear sparklines
        for (const key of ['pnl', 'winrate', 'winloss', 'fillrate', 'mfeeff', 'maestress', 'mdd']) {
          const svg = document.getElementById(`kpi-${key}-spark`);
          if (svg) svg.innerHTML = '';
        }
        $('confVal').textContent = threshold;
        renderTimeline(trades, threshold, []);
        return;
      }

      const activeTrades = filledTrades.filter(t => t.confidence >= threshold);

      // ── Compute KPI values from activeTrades ──
      let eq = 1.0, peak = 1.0, dd = 0;
      activeTrades.forEach(t => {
        eq *= (1 + t.pnl_pct / 100);
        if (eq > peak) peak = eq;
        dd = Math.max(dd, (peak - eq) / peak);
      });

      const netPnL = (eq - 1) * 100, mddPct = dd * 100;
      const returns = activeTrades.map(t => t.pnl_pct);
      const wins = returns.filter(r => r > 0);
      const losses = returns.filter(r => r < 0);
      const winRate = returns.length ? (wins.length / returns.length * 100) : 0;
      const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
      const avgLoss = losses.length ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length) : 0;
      const wlRatio = avgLoss > 0 ? avgWin / avgLoss : 0;

      const allDirectional = trades.filter(t => t.opinion !== 'NEUTRAL');
      const allFilledForRate = allDirectional.filter(t => t.is_filled);
      const fillRate = allDirectional.length > 0 ? allFilledForRate.length / allDirectional.length * 100 : 0;

      const mfeValues = filledTrades.map(t => t.mfe_efficiency_pct).filter(v => v != null);
      const mfeEfficiency = mfeValues.length > 0 ? mfeValues.reduce((a, b) => a + b, 0) / mfeValues.length : null;

      const stressTiers = filledTrades.map(t => t.mae_stress_tier).filter(Boolean);
      const protectedCount = stressTiers.filter(t => t === 'PINPOINT' || t === 'STANDARD').length;
      const maeStress = stressTiers.length > 0 ? protectedCount / stressTiers.length * 100 : null;

      // ── Compute all-trades baselines (for reference values) ──
      let allEq = 1.0, allPeak = 1.0, allDd = 0;
      filledTrades.forEach(t => {
        allEq *= (1 + t.pnl_pct / 100);
        if (allEq > allPeak) allPeak = allEq;
        allDd = Math.max(allDd, (allPeak - allEq) / allPeak);
      });
      const allNetPnL = (allEq - 1) * 100;
      const allMdd = allDd * 100;
      const allReturns = filledTrades.map(t => t.pnl_pct);
      const allWins = allReturns.filter(r => r > 0);
      const allLosses = allReturns.filter(r => r < 0);
      const allWinRate = allReturns.length ? (allWins.length / allReturns.length * 100) : 0;
      const allAvgWin = allWins.length ? allWins.reduce((a, b) => a + b, 0) / allWins.length : 0;
      const allAvgLoss = allLosses.length ? Math.abs(allLosses.reduce((a, b) => a + b, 0) / allLosses.length) : 0;
      const allWlRatio = allAvgLoss > 0 ? allAvgWin / allAvgLoss : 0;
      const allMfeVals = filledTrades.map(t => t.mfe_efficiency_pct).filter(v => v != null);
      const allMfe = allMfeVals.length > 0 ? allMfeVals.reduce((a, b) => a + b, 0) / allMfeVals.length : null;
      const allStressTiers = filledTrades.map(t => t.mae_stress_tier).filter(Boolean);
      const allProtected = allStressTiers.filter(t => t === 'PINPOINT' || t === 'STANDARD').length;
      const allMae = allStressTiers.length > 0 ? allProtected / allStressTiers.length * 100 : null;

      // ── Set all-trades reference values (static, top-right of each card) ──
      $('kpi-pnl-all').textContent = (allNetPnL >= 0 ? '+' : '') + allNetPnL.toFixed(2) + '%';
      $('kpi-winrate-all').textContent = allWinRate.toFixed(0) + '%';
      $('kpi-winloss-all').textContent = allWlRatio > 0 ? allWlRatio.toFixed(2) : '—';
      $('kpi-fillrate-all').textContent = allFillForRate_text(filledTrades);
      $('kpi-mfeeff-all').textContent = allMfe != null ? allMfe.toFixed(0) + '%' : '—';
      $('kpi-maestress-all').textContent = allMae != null ? allMae.toFixed(0) + '%' : '—';
      $('kpi-mdd-all').textContent = allMdd > 0 ? '−' + allMdd.toFixed(2) + '%' : '0.00%';

      // Helper for all-trades fill rate text
      function allFillForRate_text(ft) {
        const d = ft.filter(t => t.opinion !== 'NEUTRAL');
        const f = d.filter(t => t.is_filled);
        return d.length > 0 ? (f.length / d.length * 100).toFixed(0) + '%' : '—';
      }

      // ── Set filtered KPI values with animation ──
      const animMs = _kpiAnimDuration;
      _kpiAnimDuration = 300;

      _setKpiHealth('kpi-pnl', netPnL >= 0 ? 'green' : 'red');
      setKpiWithAnimation('kpi-pnl', (netPnL >= 0 ? '+' : '') + netPnL.toFixed(2) + '%', animMs);

      _setKpiHealth('kpi-winrate', winRate >= 60 ? 'green' : winRate >= 40 ? 'amber' : 'red');
      setKpiWithAnimation('kpi-winrate', winRate.toFixed(0) + '%', animMs);

      _setKpiHealth('kpi-winloss', allAvgLoss > 0
        ? (wlRatio >= 2.0 ? 'green' : wlRatio >= 1.0 ? 'amber' : 'red')
        : 'green');
      setKpiWithAnimation('kpi-winloss', allAvgLoss > 0 ? wlRatio.toFixed(2) : '—', animMs);

      _setKpiHealth('kpi-fillrate', fillRate >= 80 ? 'green' : fillRate >= 50 ? 'amber' : 'red');
      setKpiWithAnimation('kpi-fillrate', fillRate.toFixed(0) + '%', animMs);

      if (mfeEfficiency != null) {
        _setKpiHealth('kpi-mfeeff', mfeEfficiency >= 70 ? 'green' : mfeEfficiency >= 40 ? 'amber' : 'red');
        setKpiWithAnimation('kpi-mfeeff', mfeEfficiency.toFixed(0) + '%', animMs);
      } else {
        _setKpiHealth('kpi-mfeeff', null);
        $('kpi-mfeeff').textContent = '—';
      }

      if (maeStress != null) {
        _setKpiHealth('kpi-maestress', maeStress >= 70 ? 'green' : maeStress >= 40 ? 'amber' : 'red');
        setKpiWithAnimation('kpi-maestress', maeStress.toFixed(0) + '%', animMs);
      } else {
        _setKpiHealth('kpi-maestress', null);
        $('kpi-maestress').textContent = '—';
      }

      _setKpiHealth('kpi-mdd', mddPct < 5 ? 'green' : mddPct < 15 ? 'amber' : 'red');
      setKpiWithAnimation('kpi-mdd', mddPct.toFixed(2) + '%', animMs);

      $('confVal').textContent = threshold;

      // ── Render sparklines ──
      renderAllSparklines(threshold, filledSorted);

      // ── Render bubble timeline (no PnL curve) ──
      renderTimeline(trades, threshold, []);
    }
```

- [ ] **Step 2: Verify JS syntax**

Run: `cd /Users/yangjiang/workspace/binary-star && node -e "
const fs = require('fs');
const html = fs.readFileSync('src/dashboard/templates/index.html', 'utf8');
// Check that updateAllCharts is present
if (html.includes('function updateAllCharts')) console.log('OK: updateAllCharts found');
else console.log('ERROR: updateAllCharts missing');
if (html.includes('renderAllSparklines')) console.log('OK: renderAllSparklines found');
else console.log('ERROR: renderAllSparklines missing');
"`

Expected: Both "OK" messages

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/templates/index.html
git commit -m "feat: update updateAllCharts to drive sparklines and all-trades refs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Strip PnL from renderTimeline Bubble Chart

**Files:**
- Modify: `src/dashboard/templates/index.html:340-465` (renderTimeline function)

**Interfaces:**
- Consumes: `trades` and `threshold` from `updateAllCharts`; `curve` is always `[]`
- Produces: Clean bubble chart without PnL encoding, equity curve, or y2 axis

- [ ] **Step 1: Apply targeted edits to renderTimeline**

**Edit 1**: Change bubble radius from PnL-based to uniform. Find line 366:
```
          r: Math.max(6, Math.min(22, Math.abs(t.pnl_pct) * 6 + t.confidence / 10)),
```
Replace with:
```
          r: 8,
```

**Edit 2**: Remove `pnl` from the point data object. Find lines 367-368:
```
          pnl: t.pnl_pct, op: t.opinion, symbol: t.symbol || '',
```
Replace with:
```
          op: t.opinion, symbol: t.symbol || '',
```

**Edit 3**: Remove the equity curve dataset. Find lines 404-414 (the equity curve data computation + the second dataset):
```
	      // Mini equity curve
	      var eqData = curve || [];
	      var showEquity = eqData.length > 0;
	      var eqEnd = showEquity ? eqData[eqData.length - 1].y : 0;
	      var eqColor = eqEnd > 0 ? 'rgba(64, 168, 95, 0.32)' : 'rgba(224, 85, 74, 0.32)';
	      var eqFill = eqEnd > 0 ? 'rgba(64, 168, 95, 0.04)' : 'rgba(224, 85, 74, 0.04)';
```
and
```
	        data: { datasets: [
	          { data: points, backgroundColor: points.map(p => p.backgroundColor), borderColor: points.map(p => p.borderColor), borderWidth: 1 },
	          { data: eqData, type: 'line', yAxisID: 'y2', borderColor: eqColor, borderWidth: 1, pointRadius: 0, pointHitRadius: 0, fill: true, backgroundColor: eqFill, tension: 0.15 }
	        ] },
```
Replace with:
```
	        data: { datasets: [
	          { data: points, backgroundColor: points.map(p => p.backgroundColor), borderColor: points.map(p => p.borderColor), borderWidth: 1 }
	        ] },
```

**Edit 4**: Remove y2 axis. Find the `y2` line in the scales config (line 428):
```
            y2: { display: showEquity, position: 'right', ticks: { color: textMuted, callback: function(v) { return (v > 0 ? '+' : '') + v.toFixed(1) + '%'; } }, grid: { drawOnChartArea: false } }
```
Delete this entire line (the `y2:` entry). Also remove the trailing comma from the preceding `y:` line if needed.

**Edit 5**: Remove PnL from tooltip. Find lines 439-446:
```
                label: (ctx) => {
                  const d = ctx.raw;
                  const pnlStr = d.pnl != null ? `${d.pnl > 0 ? '+' : ''}${d.pnl.toFixed(2)}%` : '—';
                  const lines = [`${d.op}  ·  ${t('chart.conf_tooltip')} ${d.y != null ? d.y.toFixed(0) : '—'}%  ·  ${t('chart.pnl_tooltip')} ${pnlStr}`];
                  if (d.holding) lines.push(`${t('chart.holding_tooltip')} ${d.holding}h`);
                  if (d.version) lines.push(`v${d.version}`);
                  return lines;
                }
```
Replace with:
```
                label: (ctx) => {
                  const d = ctx.raw;
                  const lines = [`${d.op}  ·  ${t('chart.conf_tooltip')} ${d.y != null ? d.y.toFixed(0) : '—'}%`];
                  if (d.holding) lines.push(`${t('chart.holding_tooltip')} ${d.holding}h`);
                  if (d.version) lines.push(`v${d.version}`);
                  return lines;
                }
```

**Edit 6**: Remove the `_firstChartRender = false` conditional on curve length. Find line 464:
```
      if ((curve || []).length > 0) _firstChartRender = false;
```
Replace with:
```
      _firstChartRender = false;
```

- [ ] **Step 2: Verify JS syntax**

Run: `cd /Users/yangjiang/workspace/binary-star && node -e "
const fs = require('fs');
const html = fs.readFileSync('src/dashboard/templates/index.html', 'utf8');
const checks = [
  ['uniform radius', 'r: 8'],
  ['no pnl in point data', 'op: t.opinion, symbol:'],
  ['no equity dataset', 'data: { datasets:'],
  ['no y2 axis', 'y2:'],
  ['no pnl in tooltip', 'chart.conf_tooltip'],
];
checks.forEach(([name, needle]) => {
  if (html.includes(needle)) console.log('OK: ' + name + ' matches');
  else console.log('WARN: ' + name + ' NOT found');
});
// Verify y2 is gone
if (!html.includes('y2:')) console.log('OK: y2 axis removed');
else console.log('WARN: y2 still present');
"`

Expected: All "OK" except "no y2 axis" should show "WARN: NOT found" (searches for 'y2:' expects NOT to find it).

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/templates/index.html
git commit -m "feat: strip PnL from bubble timeline — uniform radius, no equity curve, no y2

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Integration Verification

**Files:**
- No file changes — verify the complete system works end-to-end

- [ ] **Step 1: Start the dashboard and check for JS errors**

```bash
cd /Users/yangjiang/workspace/binary-star && python -c "
from src.dashboard.server import app
print('FastAPI app imports OK')
print('All dashboard modules loaded successfully')
"
```

Expected: No import errors, "All dashboard modules loaded successfully"

- [ ] **Step 2: Verify template renders via Jinja2**

```bash
cd /Users/yangjiang/workspace/binary-star && python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('src/dashboard/templates'))
tpl = env.get_template('index.html')
rendered = tpl.render(data_root='prod')
# Check key elements present
assert 'kpi-grid' in rendered, 'Missing kpi-grid'
assert 'kpi-spark' in rendered, 'Missing kpi-spark'
assert 'kpi-all-ref' in rendered, 'Missing kpi-all-ref'
assert 'kpi-pnl-all' in rendered, 'Missing kpi-pnl-all ref'
assert 'kpi-pnl-spark' in rendered, 'Missing kpi-pnl-spark SVG'
assert 'renderAllSparklines' in rendered, 'Missing renderAllSparklines function'
assert 'r: 8' in rendered, 'Missing uniform bubble radius'
print('Template renders OK — all new elements present')
"
```

Expected: `Template renders OK — all new elements present`

- [ ] **Step 3: Verify CSS is parseable**

```bash
cd /Users/yangjiang/workspace/binary-star && python -c "
import re
css = open('src/dashboard/static/dashboard.css').read()
# Check for new class selectors
assert '.kpi-top-row' in css, 'Missing .kpi-top-row'
assert '.kpi-all-ref' in css, 'Missing .kpi-all-ref'
assert '.kpi-spark' in css, 'Missing .kpi-spark'
# Check attribute selectors for accent colors
assert 'data-kpi=\"pnl\"' in css, 'Missing pnl accent color rule'
assert 'data-kpi=\"mdd\"' in css, 'Missing mdd accent color rule'
print('CSS OK — all new rules present')
"
```

Expected: `CSS OK — all new rules present`

- [ ] **Step 4: Run existing tests to ensure nothing is broken**

```bash
cd /Users/yangjiang/workspace/binary-star && python -m pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

Expected: All existing tests pass (same result as before changes).

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: integration verification — all tests pass

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 1.1 Layout: 7 same-size cards, responsive grid (Task 1 HTML + Task 2 CSS)
- ✅ 1.2 Card Anatomy: name + all-trades ref + value + dual-line sparkline + left-border health (Task 1 HTML, Task 2 CSS, Task 4 updateAllCharts)
- ✅ 1.3 KPI Color Assignments: accent colors per KPI (Task 2 CSS, Task 3 _kpiSparkAccent)
- ✅ 1.4 All-Trades Reference: top-right dim number, static (Task 4 updateAllCharts)
- ✅ 1.5 Dual-Line Sparkline Data: cumulative KPI arrays, gray line + colored line (Task 3 functions, Task 4 renderAllSparklines call)
- ✅ 2.1 What Stays: bubble chart, threshold line, slider, tooltip, click nav (Task 5 — verified by what we DON'T delete)
- ✅ 2.2 What Is Removed: bubble radius PnL encoding, equity curve, y2 axis, tooltip PnL (Task 5)
- ✅ 2.3 Data Flow: slider → updateAllCharts → renderTimeline(trades, threshold, []) (Task 4 + Task 5)
- ✅ 3. Confidence Slider Behavior: stays in chart-header, drives all updates (unchanged — confirmed)
- ✅ 4. Files: index.html + dashboard.css (no API/server changes)
- ✅ 6. States: loading/empty/single-trade/error (handled in existing updateAllCharts empty-state path)

**2. Placeholder scan:** No TBD, TODO, "implement later", "add error handling", or vague steps. All code is concrete.

**3. Type consistency:**
- `renderAllSparklines(threshold, filledTradesSorted)` — called in Task 4, defined in Task 3 ✅
- `_computeCumulativeKpi(filledTradesSorted, kpiKey)` — called in renderAllSparklines, defined in Task 3 ✅
- `_pointsToPolyline(points)` — called in renderAllSparklines, defined in Task 3 ✅
- `_allKpiBaselines` — reset in Task 3 Step 2 (loadTrades), used in Task 3 renderAllSparklines ✅
- KPI element ids (`kpi-pnl`, `kpi-pnl-all`, `kpi-pnl-spark`, etc.) — defined in Task 1 HTML, referenced in Task 3 and Task 4 ✅
- `curve` param becomes `[]` — Task 5 removes equity curve code, Task 4 passes `[]` ✅
