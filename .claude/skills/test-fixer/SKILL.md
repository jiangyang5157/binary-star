---
name: test-fixer
description: Run all tests, diagnose failures, fix broken tests or buggy code, remove redundant/overlapping tests, and split complex long-running tests. Use when the user asks to run tests, fix test failures, clean up tests, reduce test bloat, maintain the test suite, or any mention of broken/failing/flaky tests. Also trigger when the user says "跑测试", "修复测试", "test", "pytest", or wants to verify their changes pass tests.
---

# Test Fixer

Run the full test suite, diagnose every failure, and automatically fix all issues. Then scan the test suite for bloat — redundant tests, overlapping coverage, and overly complex tests that should be split.

## Why This Matters

A test suite decays over time. Tests break when APIs change, copy-paste creates near-duplicates, and "just one more assertion" grows tests into unmaintainable monoliths. Running `pytest` and seeing 20 failures is demoralizing — but many of those failures are tests that drifted from the code, not bugs.

This skill treats test health as a first-class concern: fix what's broken, remove what's dead weight, and simplify what's overgrown.

## Workflow

### Step 0: Choose Mode

At the very start, ask the user which mode to run:

| Option | Scope |
|------|-------|
| **Quick Fix** (default) | Step 1 → Step 2 → Step 5 → Step 6. Run tests, fix failures, report, verify. |
| **Full Audit** | Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6. Everything in Quick Fix plus redundancy removal and complex test splitting. |

Default to Quick Fix. If the user confirms without choosing, run Quick Fix. Only run Full Audit when explicitly selected.

---

### Step 1: Run Tests

Run the full suite and capture structured output:

```bash
python -m pytest tests/ -v --tb=short --durations=10 2>&1
```

Extract:
- Every failed test: full nodeid (e.g., `tests/unit/test_config.py::test_regime_config_loads_from_yaml`), error type, traceback
- Slowest tests from `--durations`
- Any warnings or import-level errors

If the test run itself crashes (segfault, import error in conftest, etc.), fix that first — it blocks everything else.

### Step 2: Diagnose Failures

For each failed test, read both the **test** and the **code it exercises** to determine root cause. Never guess from the traceback alone — a traceback tells you where it crashed, not why.

Classify every failure into one of:

| Classification | Signal | Fix |
|---|---|---|
| **CODE_BUG** | Crash (AttributeError, TypeError, ImportError from src/), logic error where the test expectation is correct, regression from recent changes | Fix the source code |
| **TEST_BUG** | Assertion uses wrong expected value, mock not configured correctly, test calls deprecated API, test assumes stale return type | Fix the test |
| **ENV** | Missing pip package, config file not found, environment variable unset | Fix the environment or skip with reason |

**How to tell CODE_BUG from TEST_BUG:** Read the function signature and docstring in the source. If the test expects behavior the function clearly wasn't designed to provide, it's a TEST_BUG. If the function should handle the case but doesn't (e.g., returns None when it should return a dict, or crashes on valid input), it's a CODE_BUG. When genuinely uncertain, lean toward CODE_BUG — a test that breaks when the code changes is a healthy test, and we shouldn't weaken it without strong evidence.

### Step 3: Detect and Remove Redundancy

Scan all test files for tests that don't earn their keep. Delete them — don't comment out, don't skip, don't `@pytest.mark.skip`. Delete.

**Duplicates** — two or more tests that exercise the same code path with the same inputs and same assertions. Keep the better-named one.

**Strict subsets** — test A checks X; test B checks X + Y + Z on the same function. Test A adds nothing. Delete A.

**Trivial tests** — tests whose only assertions are `isinstance` checks or attribute-exists checks on dataclass/config objects, when other tests already exercise those fields meaningfully. A test that says "this config field is a float" doesn't help when an integration test already exercises that config value end-to-end.

**Near-identical parameterizations** — `@pytest.mark.parametrize` with multiple cases that test effectively the same thing. Consolidate to the minimal set that covers distinct edge cases.

When deleting, explain in the report: what was deleted, why it was safe, and which remaining test covers that behavior.

### Step 4: Split Complex Tests

Identify tests that should be split using these heuristics:
- Test function body > 40 lines
- More than 4 conceptually distinct assertion groups (separated by blank lines or comments)
- Tests multiple unrelated behaviors of the same function
- Takes > 500ms (check `--durations=0` output)

A good test tests **one behavior**. A test named `test_debate_loop` that verifies early exit, history compression, math check invocation, and edge cases is doing too much.

For each candidate:
1. Identify the distinct behaviors being tested
2. Create a focused test for each behavior, with a descriptive name
3. After splitting, cross-check against existing tests — if a newly-split test overlaps with an existing one, keep only the better one
4. Delete the original monolithic test

**Splitting is not always right.** If the long test is an end-to-end flow where each step depends on the previous one (e.g., "create order → modify → cancel"), keep it together — splitting would create fragile tests that need complex setup to mimic the earlier steps.

### Step 5: Report

Present a summary table in conversation:

```
## Test Suite Report

### Failures Fixed (N)
| 测试 | 分类 | 修复说明 |
|------|------|---------|
| test_x | CODE_BUG | src/x.py L42: 修复了 xxx |
| test_y | TEST_BUG | 更新 mock 参数匹配新接口 |

### Redundant Tests Removed (N)
| 删除的测试 | 原因 | 被谁覆盖 |
|-----------|------|---------|
| test_foo | 与 test_bar 重复 | tests/unit/test_x.py::test_bar |

### Tests Split (N)
| 原测试 | 拆分为 |
|--------|--------|
| test_big | test_a, test_b, test_c |
```

### Step 6: Verify

Run the suite again to confirm everything passes:

```bash
python -m pytest tests/ -v --tb=short
```

If anything still fails, loop back to Step 2. Don't stop until the suite is green.

## Important Rules

- **Fix failures before removing redundancy.** Don't delete a test because it's "redundant" when the real problem is that the code it tests is broken.
- **Read the source code.** Never classify a failure without reading both the test and the function it calls. The traceback is a starting point, not a diagnosis.
- **Delete, don't skip.** `@pytest.mark.skip` leaves dead code. If a test is redundant or worthless, remove it.
- **One behavior per test after splitting.** If you can't name a split test with a clear `test_<what>_<outcome>` pattern, the split isn't right yet.
- **Verify after every change.** Run `pytest` after fixing each category to catch regressions early.
