"""Pin the effective pre-AI gate values for BTC/XAUT.

Why this test exists
--------------------
`min_active_non_trend` was introduced on 2026-07-18 with value 2, then flipped
five times (2→3, 3→2, 2→3, 3→2, 2→3) up to 2026-08-26 — each time without A/B
evidence and without updating the inline comment.  That is exactly why the
comment in `symbol_config.yaml` read "从 3 降回 2" while the value was 3.

None of those flips came from `run_patch.py`: across 23 stored evolution
proposals (61 patch entries) not one targeted a `sniper.*` path.  So the guard
belongs here — at the *effective resolved value* — rather than in the patch
pipeline, where it would only cover one of several possible writers.

The measurement behind the current values (2026-09-05 → 09-17, 3158 pulses,
22 wakes) is in `docs/sniper_gate_review_and_plan_20260917.md`:
  * lowering to 2 multiplies wakes 1.28/day → ~9.5/day (XAUT) and
    0.16/day → ~3.0/day (BTC), while the marginal candidates keep a negative
    1h drift-adjusted excess return;
  * the ≥3 cohort is the *worst* measured cohort (MAE −1.47 ATR, 56% would hit
    −1 ATR first), so 3 is a volume cap, not a quality filter.

To change these values intentionally: update EXPECTED below and attach the new
measurement to that document in the same commit.
"""
import pytest

EXPECTED = {
    'XAUTUSDT': {'min_active_non_trend': 3, 'min_active_trend': 1},
    'BTCUSDT': {'min_active_non_trend': 3, 'min_active_trend': 1},
}


def _effective_gate(symbol):
    from src.utils.pipeline_utils import load_global_config
    from src.config.symbol_resolver import resolve_config

    resolved = resolve_config(load_global_config(), symbol)
    return resolved['sniper']['signal_stack']['gate']


@pytest.mark.parametrize('symbol', sorted(EXPECTED))
def test_effective_gate_values_are_pinned(symbol):
    gate = _effective_gate(symbol)
    got = {key: gate.get(key) for key in EXPECTED[symbol]}
    assert got == EXPECTED[symbol], (
        f"[{symbol}] effective pre-AI gate changed: {got} != {EXPECTED[symbol]}. "
        "This value is frozen pending A/B evidence — see "
        "docs/sniper_gate_review_and_plan_20260917.md. If the change is "
        "intentional, update EXPECTED in this test and attach the measurement."
    )


@pytest.mark.parametrize('symbol', sorted(EXPECTED))
def test_independent_direction_rule_stays_in_shadow_mode(symbol):
    """The provenance rule must stay non-enforcing until the shadow period is
    evaluated (S2/S3 in the plan).  Flipping it on is a behaviour change and
    must be a deliberate, separate commit."""
    gate = _effective_gate(symbol)
    assert gate.get('require_independent_direction') is False, (
        f"[{symbol}] require_independent_direction is enabled. Per "
        "docs/sniper_gate_review_and_plan_20260917.md this may only be turned "
        "on after the shadow-period acceptance criteria are met."
    )
    assert gate.get('shadow_require_independent_direction') is True, (
        f"[{symbol}] shadow_require_independent_direction is off — the shadow "
        "evidence for S2 will not accumulate."
    )
