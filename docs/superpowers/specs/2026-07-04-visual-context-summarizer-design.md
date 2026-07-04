# Visual Context Summarizer — Design Spec

**Date:** 2026-07-04
**Status:** Approved
**Scope:** `extract_visual_summary` path for non-vision LLM models (DeepSeek, Qwen)

---

## 1. Problem

When `supports_vision=False` (DeepSeek, Qwen), chart images (`.png`) are silently skipped in `build_messages()`. The prompts (`session.md`, `critic.md`) reference `VISUAL_CONTEXT: MACRO_SNAPSHOT` and `VISUAL_CONTEXT: MICRO_SNAPSHOT` as if they exist, but the model never sees them. All spatial/structural information in the charts — candlestick morphology, volume profile shape, price ladder ordering, liquidation cluster proximity — is invisible to the strategy LLM.

## 2. Solution

**Always generate both `.png` and `.md`** from chart source data. At inference time, branch on `supports_vision`:

| `supports_vision` | Visual channel | Report paths |
|---|---|---|
| `True` (Gemini) | `.png` images via `VisualPart` (unchanged) | `.png` (unchanged) |
| `False` (DeepSeek, Qwen) | `.md` text injected into prompt | `.md` (corrected) |

The `.md` files are **self-contained textual twins** of the charts — they contain all information visible in the image, structured for LLM consumption. No cross-referencing with `observation_json` required.

## 3. Architecture

### 3.1 New Component: `VisualContextSummarizer`

**Location:** `src/analyzer/visual_context_summarizer.py`

Receives the **identical data inputs** as `ChartGenerator.generate_chart()`:

```python
def generate(
    symbol: str,
    df: pd.DataFrame,           # OHLCV + indicator columns
    profile_data: Dict[str, Any],  # poc, vah, val, profile_data histogram
    liquidations: Union[List, Dict],  # long/short liquidation clusters
    time_interval: str,          # '1h', '15m', etc.
    atr: Optional[float],        # ATR for scaling context
) -> str:                        # formatted markdown text
```

**Design invariant:** Same source data → pixel-level numerical consistency between `.png` chart and `.md` summary. No OCR, no image parsing.

### 3.2 Data Flow

```
MarketObserver._generate_snapshots()
  ├── chart_gen.generate_chart()        → macro_snapshot.png  (existing)
  ├── chart_gen.generate_chart()        → micro_snapshot.png  (existing)
  ├── summarizer.generate()             → macro_snapshot_summary.md  (NEW)
  └── summarizer.generate()             → micro_snapshot_summary.md  (NEW)
              │
              ▼ observation["visual_context"]:
                  "macro_snapshot":          "...png"  (existing)
                  "micro_snapshot":          "...png"  (existing)
                  "macro_snapshot_summary":  "...md"   (NEW)
                  "micro_snapshot_summary":  "...md"   (NEW)
              │
              ▼ BinaryStarOrchestrator._load_visual_assets():
                  if supports_vision → read .png → List[VisualPart]
                  if not              → read .md  → visual_context_text: str
              │
              ▼ Report path correction (non-vision only):
                  vc["macro_snapshot"] = vc["macro_snapshot_summary"]
                  vc["micro_snapshot"] = vc["micro_snapshot_summary"]
              │
              ▼ Prompt injection (non-vision only):
                  prompt += "\n\n" + visual_context_text
```

### 3.3 File Naming

```
klines/
  BTCUSDT_klines_1h_20260704_093000.png   ← chart image
  BTCUSDT_klines_1h_20260704_093000.md    ← visual summary (same basename)
  BTCUSDT_klines_15m_20260704_093000.png
  BTCUSDT_klines_15m_20260704_093000.md
```

## 4. VISUAL_CONTEXT Text Format

Six self-contained sections per snapshot. All data extracted directly from chart source — no dependency on `observation_json`.

### 4.1 Section 1: PRICE LADDER

All structural levels ordered by price, descending. Current price as visual separator. ASCII bars indicate relative strength/intensity.

```markdown
## 1. PRICE LADDER
# current_price = 97234.5

  ─── ABOVE (resistance / supply zone) ───
  98430.1  Short Liq #2     (+1.23%)  [▓▓   ]  intensity=0.31
  98201.5  HVN #1           (+0.99%)  [████]  strength=0.91
  97950.2  Short Liq #1     (+0.74%)  [▓▓▓▓]  intensity=0.82
  97812.0  VAH              (+0.59%)  [──●──]  Value Area High
  ────────────────────────────────────────────
  97234.5  ● CURRENT PRICE
  ────────────────────────────────────────────
  96810.0  POC              (−0.44%)  [████]  strength=0.94
  96450.8  HVN #2           (−0.81%)  [███ ]  strength=0.76
  96102.3  VAL              (−1.16%)  [──●──]  Value Area Low
  95780.5  Long Liq #1      (−1.50%)  [▓▓▓▓]  intensity=0.88
  95230.0  Long Liq #2      (−2.06%)  [▓▓   ]  intensity=0.35

  ATR_macro = 1240.3  |  VA_span = 1709.7 (1.76% of price)
```

**Data sources:** `df['close'].iloc[-1]`, `profile_data.{poc,vah,val}`, `nodes.{hvn,lvn}`, `liquidations.{long_liquidation,short_liquidation}`.

**Distance formula:** `(level - current_price) / current_price * 100` (2 decimal places).

### 4.2 Section 2: CANDLESTICK PANORAMA

Last 6 bars with body/wick decomposition. Volume-at-time inline.

```markdown
## 2. CANDLESTICK PANORAMA (最近 6 bars, 1h)

  T-5: [████]  BULL engulfing     O=95900  H=97250  L=95820  C=97120  (+1.2%)
        body=1220 (dominant)  upper_wick=130  lower_wick=80

  T-4: [█   ]  BEAR small body    O=97120  H=98180  L=96950  C=96850  (−0.3%)
        body=270 (small)  upper_wick=1060 (LONG ⚠)  lower_wick=100

  ...

  ─── Morphology summary ───
  Trend: 4 consecutive bullish bars
  Wick signal: T-4 LONG upper wick (rejection ~98180), T-2 lower wick (support)
  Wick skew (instant): 0.06 (extreme rejection)
```

**Data sources:** `df[['open','high','low','close']].tail(6)`.

**Formulas:**
- `body = abs(close - open)`
- `upper_wick = high - max(open, close)`
- `lower_wick = min(open, close) - low`
- `wick_skew = (close - low) / (high - low)` when `high > low`
- Direction: `close > open` → BULL, `close < open` → BEAR
- Bar type: `body/(high-low) > 0.8` → MARUBOZU, `body/(high-low) < 0.2` → DOJI

### 4.3 Section 3: VOLUME-AT-TIME PROFILE

Last 12 bars of volume relative to moving average.

```markdown
## 3. VOLUME-AT-TIME PROFILE (最近 12 bars, 1h)

  T-11: ████      1.1× MA
  T-10: █████     1.5× MA
  ...
  T-6:  ████████  2.4× MA  ← SURGE

  Volume MA (12): baseline = 1.0×
  Surge bars (>2.0× MA): T-6, T-5
  Gaps / voids detected: none
```

**Data source:** `df['volume'].tail(12)`. Volume MA computed over the lookback window.

### 4.4 Section 4: VOLUME PROFILE TOPOGRAPHY

Profile shape, node distribution, anchoring assessment.

```markdown
## 4. VOLUME PROFILE TOPOGRAPHY (1h, Gaussian σ=2.0)

  POC = 96810.0  peak_strength = 0.94  peak_type = sharp (单峰集中)
  VAH = 97812.0  |  VAL = 96102.3
  VA_span = 1709.7  |  VA_width = 1.76% of price

  ─── Profile shape ───
  Type: b-shaped (卖出尾端形态)
  POC position in VA: 38% from VAL, 62% to VAH (下半部集中)
  上方密度: 分散  |  下方密度: 集中

  ─── High Volume Nodes ───
  HVN #1 @ 96810.0  strength=0.94  type=POC  position=below_price
  HVN #2 @ 98201.5  strength=0.91  type=secondary  position=above_price

  ─── Low Volume Nodes (gaps / vacuums) ───
  LVN #1: 97400–97800  vacuum_score=0.73  width=400

  ─── Anchoring assessment ───
  Nearest anchor above: HVN #1 @ 98201.5  dist=+0.99%
  Nearest anchor below: POC @ 96810.0  dist=−0.44%
  Strongest anchor: POC (strength=0.94)
```

**Data sources:** `profile_data.{poc,vah,val,profile_data[]}`, `nodes.{hvn,lvn}`.

**Formulas:**
- `POC position in VA = (poc - val) / (vah - val) * 100`
- Profile type: `POC % < 40` → b-shaped, `POC % > 60` → P-shaped, else → balanced
- Peak type: histogram max / mean > 2.0 → sharp, else → distributed

### 4.5 Section 5: LIQUIDATION LANDSCAPE

Cluster positions with structural context.

```markdown
## 5. LIQUIDATION LANDSCAPE

  ─── SHORT liquidation clusters ───
  #1 @ 97950.2  intensity=0.82  width≈180
     Position: between VAH (97812.0) and HVN #1 (98201.5)
  #2 @ 98430.1  intensity=0.31  width≈120
     Position: above HVN #1, isolated

  ─── LONG liquidation clusters ───
  #1 @ 95780.5  intensity=0.88  width≈210
     Position: below VAL (96102.3), clear of all structural anchors
  #2 @ 95230.0  intensity=0.35  width≈140
     Position: well below VAL, isolated

  ─── Landscape summary ───
  Asymmetry: Long-dominant (total long intensity 1.23 vs short 1.13)
  Nearest cluster: Short #1 @ +0.74%
  Highest threat cluster: Long #1 @ −1.50% (intensity=0.88, structurally unshielded)
```

**Data source:** `liquidations.{long_liquidation,short_liquidation}` — each entry has `price`, `intensity`, and derived `width`.

**Cluster position classification:** Compare cluster price against VAH, VAL, and HVN prices to determine "between X and Y", "above X", "below Y", or "isolated" (no nearby structure within 1 ATR).

### 4.6 Section 6: KEY LEVELS REFERENCE

Quick-reference table of all levels.

```markdown
## 6. KEY LEVELS REFERENCE (price-descending)

  PRICE        TYPE            STR/INT   POSITION VS PRICE
  ───────────  ──────────────  ────────  ──────────────────
  98430.1      Short Liq #2    0.31      +1.23%
  98201.5      HVN #1          0.91      +0.99%
  97950.2      Short Liq #1    0.82      +0.74%
  97812.0      VAH             —         +0.59%
  ─────────────────────────────────────────────────────────
  97234.5      ● CURRENT       —         0.00%
  ─────────────────────────────────────────────────────────
  96810.0      POC             0.94      −0.44%
  96450.8      HVN #2          0.76      −0.81%
  96102.3      VAL             —         −1.16%
  95780.5      Long Liq #1     0.88      −1.50%
  95230.0      Long Liq #2     0.35      −2.06%
```

**Data source:** Aggregated from all above sections.

## 5. Code Changes

### 5.1 Files Modified

| # | File | Change |
|---|------|--------|
| 1 | `src/analyzer/visual_context_summarizer.py` | **NEW** — `VisualContextSummarizer` class (~300 lines) |
| 2 | `src/infrastructure/ai_client.py` | `AbstractAIClient.supports_vision` property (default `False`) |
| 3 | `src/infrastructure/ai/gemini_adapter.py` | `supports_vision = True` override |
| 4 | `src/analyzer/market_observer.py` | `_generate_snapshots()` — call summarizer, write `.md` files |
| 5 | `src/agent/binary_star_orchestrator.py` | `_load_visual_assets()`, path correction, pass `visual_context_text` |
| 6 | `src/agent/session_agent.py` | Accept `visual_context_text` param, inject into prompt |
| 7 | `src/agent/critic_agent.py` | Same injection logic |
| 8 | `src/agent/debate_loop.py` | Pass `visual_context_text` through to agents |
| 9 | `scripts/clean_orphan_artifacts.py` | Add `.md` to regex extension list |

### 5.2 Files NOT Modified

- `_openai_helpers.py` / `build_messages()` — zero changes (empty `visual_parts` list → natural skip)
- `chart_generator.py` / `ChartGenerator` — zero changes (unrelated concern)
- `session.md` / `critic.md` / `binary_star.md` — zero changes (prompt templates unchanged)
- `deepseek_adapter.py` / `qwen_adapter.py` — zero changes (inherit `supports_vision=False` from base)
- `global_config.yaml` — zero changes (`supports_vision` config already exists)

### 5.3 Prompt Injection

`VISUAL_CONTEXT` text is injected **after template formatting**, appended to the prompt:

```
[formatted session.md prompt with observation_json, etc.]

[VISUAL_CONTEXT: MACRO_SNAPSHOT]
# BTCUSDT — 1h STRUCTURAL PANORAMA
... (macro_snapshot_summary.md content) ...

[VISUAL_CONTEXT: MICRO_SNAPSHOT]
# BTCUSDT — 15m STRUCTURAL PANORAMA
... (micro_snapshot_summary.md content) ...
```

This preserves the `VISUAL_CONTEXT: MACRO_SNAPSHOT` / `VISUAL_CONTEXT: MICRO_SNAPSHOT` labels referenced in the prompts without modifying the template files.

## 6. Naming Convention

### 6.1 Section Headers (no conflicts)

Section headers use a distinct namespace from `observation_json` keys, prompt template variables, and config fields:

| Summary Header | Does NOT collide with |
|---|---|
| `PRICE LADDER` | No existing field |
| `CANDLESTICK PANORAMA` | No existing field |
| `VOLUME-AT-TIME PROFILE` | Distinct from `volume_profile` (JSON key) |
| `VOLUME PROFILE TOPOGRAPHY` | Same note |
| `LIQUIDATION LANDSCAPE` | Distinct from `liquidation_clusters` (JSON sub-key) |
| `KEY LEVELS REFERENCE` | No existing field |

### 6.2 Injected Labels

The labels wrapping summary content in the prompt — `[VISUAL_CONTEXT: MACRO_SNAPSHOT]` and `[VISUAL_CONTEXT: MICRO_SNAPSHOT]` — match the existing `VisualPart.label` text exactly, preserving prompt compatibility.

## 7. Clean-Orphan-Artifacts Update

**File:** `scripts/clean_orphan_artifacts.py`

**Change:** Add `.md` to the regex extension group:

```python
# Before:
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html)$')

# After:
ARTIFACT_RE = re.compile(r'^([A-Z0-9]+)_.*_(\d{8})_(\d{6})\.(json|png|html|md)$')
```

No other changes needed. `klines/` is already in the scanned directory list — `.md` files in `klines/` share the same `{symbol}_..._{timestamp}.md` pattern and the same session-key extraction logic works unchanged.

## 8. Data Precision Guarantees

All values in the `.md` summary are extracted from the **same data sources** as `ChartGenerator.generate_chart()`, guaranteeing:

| Data Point | Source | Extraction Method |
|---|---|---|
| `current_price` | `df['close'].iloc[-1]` | Direct read |
| POC, VAH, VAL | `profile_data` dict | Direct read |
| HVN/LVN prices & strengths | `nodes` dict | Direct read |
| Liquidation cluster prices & intensities | `liquidations` dict | Direct read |
| Candle OHLC | `df` rows | Direct read |
| Candle body/wick | Derived from OHLC | `abs(c-o)`, `h-max(o,c)`, `min(o,c)-l` |
| Distance % | `(level - price) / price * 100` | Float arithmetic, 2 decimal places |
| Volume ratio | `volume / volume_ma` | Float arithmetic, 1 decimal place |
| Profile shape type | Histogram analysis | POC percentile within VA range |
| ATR | `df['atr'].iloc[-1]` | Direct read |

**No float formatting:**
- Prices: 1 decimal place (matching exchange precision)
- Percentages: 2 decimal places
- Ratios (intensity, strength, volume ratio): 2 decimal places
- ATR: 1 decimal place

## 9. Self-Review

### 9.1 Placeholder Scan
- No TBDs, TODOs, or incomplete sections.

### 9.2 Internal Consistency
- Data flow is consistent: `MarketObserver` → `observation["visual_context"]` → `Orchestrator` → `DebateLoop` → `Agents`.
- Naming is consistent: `macro_snapshot_summary`/`micro_snapshot_summary` keys mirror existing `macro_snapshot`/`micro_snapshot` pattern.
- Prompt injection happens at `execute_session_cycle` / `evaluate` level — both agents get the same VISUAL_CONTEXT text.

### 9.3 Scope Check
- Single subsystem: visual summary generation + injection. No decomposition needed.

### 9.4 Ambiguity Check
- `supports_vision` branching is explicit and mutually exclusive.
- `.md` file path is derived from the same `ChartStorageManager.generate_filepath()` pattern (png → md extension swap).
- Report path correction happens once in orchestrator, before DebateLoop and before persistence.
- `clean-orphan-artifacts` regex change is minimal and backwards-compatible (`.md` in `klines/` only — no `.md` in `audits/` or `html/`).
