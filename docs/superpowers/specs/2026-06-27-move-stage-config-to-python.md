# Move Session Progress Stage Config from Frontend to Python Backend

**Date:** 2026-06-27
**Status:** approved

## Goal

Centralize session progress bar stage definitions (labels, percentage positions) in
`src/utils/progress_utils.py` as the single source of truth. The frontend becomes a
pure renderer that consumes stage config from the API response.

## Motivation

Currently `session-progress.js` hardcodes two constants:

```javascript
const STAGE_ANCHOR_POSITIONS = [0, 18, 62.5, 87.5, 100];
const STAGE_LABELS = ['Data Collection', 'Prep', 'Debate', 'Decision', 'Archive'];
```

Changing a stage label or adjusting percentage distribution requires editing both
JS (rendering) and mentally cross-referencing with the Python backend's stage
enumeration. With the config in Python, all stage-related constants live together.

## Design

### 1. Python: `src/utils/progress_utils.py`

Add a `STAGES` constant and an `enrich_progress()` helper:

```python
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
    """
    if progress is None:
        return None
    progress["stages"] = STAGES
    return progress
```

### 2. Python: API injection points

Call `enrich_progress()` at each API response boundary where a progress dict is
returned to the frontend. Do NOT persist `stages` into the on-disk status files
(it is static data; injecting at read time avoids redundant writes).

| Endpoint | File | Location |
|---|---|---|
| `GET /api/session/run-status` | `session_run.py` | Lines ~330, ~336 |
| `GET /api/sniper/status` | `sniper_run.py` | Line ~258 (`active_session["progress"]`) |
| Backtest status | `backtest.py` | Progress return path |

### 3. Frontend: `session-progress.js`

Remove the two hardcoded constants. All stage info comes from `data.stages` in
the API response.

- `data.stages` — `[{stage, label, position_pct}, ...]` (5 entries)
- `_barPct(stage)` — replaced by `data.stages[stage-1].position_pct`
- Anchor dot loop — iterate `data.stages` instead of `[1..5]`
- Label row — use `stage.label` instead of `STAGE_LABELS[j-1]`
- The `stage_label` override for stage 3 (when label != "Debate") continues to work

Backward compatibility: if `data.stages` is absent (old persisted data), the
progress bar falls back gracefully — the already-completed/failed states don't
render anchor dots anyway, and running state without stages is a no-op.

## Scope

- **In scope:** `progress_utils.py`, `session_run.py`, `sniper_run.py`, `backtest.py`, `session-progress.js`
- **Out of scope:** Changing stage count (always 5), dynamic stages, per-symbol stage config

## Testing

- Start a session via dashboard → verify 5-stage bar renders correctly
- Start sniper via dashboard → verify progress bar shows correct labels/positions
- Run backtest → verify same
- Check that modifying a stage label in `STAGES` is reflected in the UI without touching JS
