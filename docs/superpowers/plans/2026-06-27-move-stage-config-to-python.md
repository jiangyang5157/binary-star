# Move Stage Config to Python Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move session progress bar stage definitions (labels, percentage positions) from `session-progress.js` constants into `progress_utils.py` as the single source of truth, with API endpoints injecting `stages` at read time.

**Architecture:** Add a `STAGES` list constant and `enrich_progress()` helper to `progress_utils.py`. Call `enrich_progress()` at the 3 API response boundaries where progress dicts are returned to the frontend. Update `session-progress.js` to consume `data.stages` instead of hardcoded constants.

**Tech Stack:** Python (FastAPI), vanilla JavaScript

## Global Constraints

- Stage count is fixed at 5 (not dynamic)
- Do NOT persist `stages` into on-disk status files — inject at API read time only
- The `stage_label` override at stage 3 must continue to work
- Backward compatible: if `data.stages` is absent, JS should not crash

---

### Task 1: Add `STAGES` and `enrich_progress()` to `progress_utils.py`

**Files:**
- Modify: `src/utils/progress_utils.py`

**Interfaces:**
- Produces: `STAGES: list[dict]`, `enrich_progress(progress: dict | None) -> dict | None`

- [ ] **Step 1: Add STAGES constant and enrich_progress function**

```python
# Add after the existing constants (ACTIVE, COMPLETE, ERROR, _MAX_ACTIVITIES)

STAGES = [
    {"stage": 1, "label": "Data Collection", "position_pct": 0},
    {"stage": 2, "label": "Prep",            "position_pct": 18},
    {"stage": 3, "label": "Debate",          "position_pct": 62.5},
    {"stage": 4, "label": "Decision",        "position_pct": 87.5},
    {"stage": 5, "label": "Archive",         "position_pct": 100},
]


def enrich_progress(progress: dict | None) -> dict | None:
    """Inject stage definitions into a progress dict for frontend rendering.

    Returns the same dict (mutated in-place) for call-site convenience.
    Returns None if progress is None.
    """
    if progress is None:
        return None
    progress["stages"] = STAGES
    return progress
```

- [ ] **Step 2: Verify module imports cleanly**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "from src.utils.progress_utils import STAGES, enrich_progress; print(STAGES); print(enrich_progress({}))"
```

Expected: prints the stages list and the enriched dict with `"stages"` key.

- [ ] **Step 3: Commit**

```bash
git add src/utils/progress_utils.py
git commit -m "feat: add STAGES constant and enrich_progress() to progress_utils"
```

---

### Task 2: Inject `enrich_progress()` at session run-status endpoint

**Files:**
- Modify: `src/dashboard/api/session_run.py:322-337`
- Import: add `enrich_progress` to the existing import from `progress_utils` at line 12

**Interfaces:**
- Consumes: `enrich_progress(progress: dict | None) -> dict | None`
- Produces: API response `{"progress": enriched_dict}` with `"stages"` key

- [ ] **Step 1: Update import**

At line 12, change:
```python
from src.utils.progress_utils import add_activity_entry, ACTIVE, COMPLETE, ERROR
```
to:
```python
from src.utils.progress_utils import add_activity_entry, enrich_progress, ACTIVE, COMPLETE, ERROR
```

- [ ] **Step 2: Enrich progress in the running branch (line ~330)**

Change:
```python
        return {
            "running": True,
            "symbol": status.get("symbol", ""),
            "started_at": started_str,
            "elapsed_seconds": round(elapsed),
            "progress": progress,
        }
```
to:
```python
        return {
            "running": True,
            "symbol": status.get("symbol", ""),
            "started_at": started_str,
            "elapsed_seconds": round(elapsed),
            "progress": enrich_progress(progress),
        }
```

- [ ] **Step 3: Enrich progress in the idle branch (line ~336)**

Change:
```python
    return {
        "running": False,
        "last_run": status.get("last_run"),
        "progress": status.get("progress"),
    }
```
to:
```python
    return {
        "running": False,
        "last_run": status.get("last_run"),
        "progress": enrich_progress(status.get("progress")),
    }
```

- [ ] **Step 4: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "from src.dashboard.api.session_run import router; print('import ok')"
```

Expected: no import errors.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/api/session_run.py
git commit -m "feat: inject stages into session run-status API response"
```

---

### Task 3: Inject `enrich_progress()` at sniper status endpoint

**Files:**
- Modify: `src/dashboard/api/sniper_run.py:224-233`, plus import at top

**Interfaces:**
- Consumes: `enrich_progress(progress: dict | None) -> dict | None`
- Produces: `active_session["progress"]` includes `"stages"` key in API response

- [ ] **Step 1: Add import**

Add after the existing imports (around line 11):
```python
from src.utils.progress_utils import enrich_progress
```

- [ ] **Step 2: Enrich active_session progress**

In `sniper_status()`, after the elapsed-seconds update block (line ~231), add the enrichment call. Change the block at lines ~224-233 from:

```python
    active_session = status.get("active_session")
    if active_session and active_session.get("progress"):
        trig_iso = active_session.get("triggered_at_iso", "")
        if trig_iso:
            try:
                trig_dt = datetime.fromisoformat(trig_iso.replace("Z", "+00:00"))
                session_elapsed = round((datetime.now(timezone.utc) - trig_dt).total_seconds())
                active_session["progress"]["elapsed_seconds"] = max(session_elapsed, 0)
            except Exception:
                pass
```

to:

```python
    active_session = status.get("active_session")
    if active_session and active_session.get("progress"):
        trig_iso = active_session.get("triggered_at_iso", "")
        if trig_iso:
            try:
                trig_dt = datetime.fromisoformat(trig_iso.replace("Z", "+00:00"))
                session_elapsed = round((datetime.now(timezone.utc) - trig_dt).total_seconds())
                active_session["progress"]["elapsed_seconds"] = max(session_elapsed, 0)
            except Exception:
                pass
        enrich_progress(active_session["progress"])
```

- [ ] **Step 3: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "from src.dashboard.api.sniper_run import router; print('import ok')"
```

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/api/sniper_run.py
git commit -m "feat: inject stages into sniper status active_session progress"
```

---

### Task 4: Inject `enrich_progress()` at backtest status endpoint

**Files:**
- Modify: `src/dashboard/api/backtest.py:548-587`
- Import: add `enrich_progress` to the import at line 8

**Interfaces:**
- Consumes: `enrich_progress(progress: dict | None) -> dict | None`
- Produces: each sample's `progress` in the API response includes `"stages"` key

- [ ] **Step 1: Update import**

At line 8, change:
```python
from src.utils.progress_utils import add_activity_entry, ACTIVE, COMPLETE, ERROR
```
to:
```python
from src.utils.progress_utils import add_activity_entry, enrich_progress, ACTIVE, COMPLETE, ERROR
```

- [ ] **Step 2: Enrich each sample's progress in get_status()**

In `get_status()`, after computing the `overall` summary (line ~567) and before returning, add enrichment for each sample. Insert after line ~567 (`status["overall"] = None`):

```python
    # Inject stage config into each sample's progress for frontend rendering
    if status.get("samples"):
        for sample in status["samples"]:
            enrich_progress(sample.get("progress"))
```

- [ ] **Step 3: Verify**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "from src.dashboard.api.backtest import router; print('import ok')"
```

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/api/backtest.py
git commit -m "feat: inject stages into backtest sample progress"
```

---

### Task 5: Update frontend to consume `data.stages`

**Files:**
- Modify: `src/dashboard/static/session-progress.js`

**Interfaces:**
- Consumes: `data.stages` — `[{stage, label, position_pct}, ...]` (5 entries)
- Produces: same visual output, but driven by API data instead of hardcoded constants

- [ ] **Step 1: Remove hardcoded constants (lines 16-17)**

Delete:
```javascript
const STAGE_ANCHOR_POSITIONS = [0, 18, 62.5, 87.5, 100]; // % left for stages 1-5
const STAGE_LABELS = ['Data Collection', 'Prep', 'Debate', 'Decision', 'Archive'];
```

- [ ] **Step 2: Update _barPct() to use data.stages**

Change `_barPct(stage)` from:
```javascript
  _barPct(stage) {
    if (stage <= 0) return 0;
    if (stage >= 5) return 100;
    return STAGE_ANCHOR_POSITIONS[stage - 1];
  }
```
to:
```javascript
  _barPct(stage, stages) {
    if (stage <= 0) return 0;
    if (!stages || !stages.length) return 0;
    if (stage >= stages.length) return 100;
    return stages[stage - 1].position_pct;
  }
```

- [ ] **Step 3: Update _renderRunning() to use data.stages**

Replace the anchor dots loop (lines 96-102) from:
```javascript
    for (var i = 1; i <= 5; i++) {
      var cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' active';
      html += '<div class="' + cls + '" style="left:' +
        STAGE_ANCHOR_POSITIONS[i - 1] + '%"></div>';
    }
```
to:
```javascript
    var stages = data.stages || [];
    for (var i = 0; i < stages.length; i++) {
      var stg = stages[i];
      var cls = 'sp-anchor s' + stg.stage;
      if (stg.stage < stage) cls += ' done';
      else if (stg.stage === stage) cls += ' active';
      html += '<div class="' + cls + '" style="left:' +
        stg.position_pct + '%"></div>';
    }
```

Replace the labels row (lines 108-116) from:
```javascript
      for (var j = 1; j <= 5; j++) {
        var lblCls = 'sp-label';
        if (j < stage) lblCls += ' done';
        else if (j === stage) lblCls += ' active';
        var lblText = STAGE_LABELS[j - 1];
        if (j === 3 && label && label !== 'Debate') lblText = label;
        html += '<span class="' + lblCls + '">' + this._esc(lblText) + '</span>';
      }
```
to:
```javascript
      for (var j = 0; j < stages.length; j++) {
        var stg2 = stages[j];
        var lblCls = 'sp-label';
        if (stg2.stage < stage) lblCls += ' done';
        else if (stg2.stage === stage) lblCls += ' active';
        var lblText = stg2.label;
        if (stg2.stage === 3 && label && label !== 'Debate') lblText = label;
        html += '<span class="' + lblCls + '">' + this._esc(lblText) + '</span>';
      }
```

Update the bar fill call (line 94) from:
```javascript
    var fillPct = this._barPct(stage);
```
to:
```javascript
    var fillPct = this._barPct(stage, stages);
```

- [ ] **Step 4: Update _renderFailed() to use data.stages**

Replace the anchor dots loop (lines 205-212) from:
```javascript
    for (var i = 1; i <= 5; i++) {
      var cls = 'sp-anchor s' + i;
      if (i < stage) cls += ' done';
      else if (i === stage) cls += ' failed';
      html += '<div class="' + cls + '" style="left:' +
        STAGE_ANCHOR_POSITIONS[i - 1] + '%"></div>';
    }
```
to:
```javascript
    var stages = data.stages || [];
    for (var i = 0; i < stages.length; i++) {
      var stg = stages[i];
      var cls = 'sp-anchor s' + stg.stage;
      if (stg.stage < stage) cls += ' done';
      else if (stg.stage === stage) cls += ' failed';
      html += '<div class="' + cls + '" style="left:' +
        stg.position_pct + '%"></div>';
    }
```

Replace the labels row (lines 217-223) from:
```javascript
      for (var j = 1; j <= 5; j++) {
        var lblCls = 'sp-label';
        if (j < stage) lblCls += ' done';
        else if (j === stage) lblCls += ' failed';
        html += '<span class="' + lblCls + '">' + STAGE_LABELS[j - 1] + '</span>';
      }
```
to:
```javascript
      for (var j = 0; j < stages.length; j++) {
        var stg2 = stages[j];
        var lblCls = 'sp-label';
        if (stg2.stage < stage) lblCls += ' done';
        else if (stg2.stage === stage) lblCls += ' failed';
        html += '<span class="' + lblCls + '">' + stg2.label + '</span>';
      }
```

Update the bar fill call (line 197) from:
```javascript
    var fillPct = this._barPct(stage);
```
to:
```javascript
    var fillPct = this._barPct(stage, stages);
```

- [ ] **Step 5: Verify syntax**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && node --check src/dashboard/static/session-progress.js
```

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/static/session-progress.js
git commit -m "refactor: consume stage config from API data.stages instead of hardcoded constants"
```

---

### Task 6: Integration smoke test

**Files:**
- No code changes — verification only

- [ ] **Step 1: Verify full import chain**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -c "
from src.utils.progress_utils import STAGES, enrich_progress
from src.dashboard.api.session_run import router as sr
from src.dashboard.api.sniper_run import router as snr
from src.dashboard.api.backtest import router as br
print('All imports OK')
print('STAGES:', STAGES)
p = enrich_progress({'status': 'running', 'current_stage': 2})
print('Enriched:', 'stages' in p)
"
```

Expected: `All imports OK`, prints STAGES, `Enriched: True`

- [ ] **Step 2: Verify JS syntax check**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && node --check src/dashboard/static/session-progress.js && echo "JS OK"
```

Expected: `JS OK`

- [ ] **Step 3: Run existing tests**

```bash
cd /Users/yangjiang/Documents/workspace/crypto && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: existing tests still pass (no regressions).

- [ ] **Step 4: Commit final verification**

```bash
git add -A
git commit -m "chore: integration smoke test passed"
```
