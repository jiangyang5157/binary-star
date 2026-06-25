---
name: sync-project-docs
description: Use when the user asks to update, sync, audit, or refresh CLAUDE.md, README.md, or project documentation to match the current codebase state. Also use when the project has evolved through many commits and documentation may have drifted from reality — new files, deleted modules, renamed classes, changed commands, shifted architecture.
---

# Sync Project Documentation

## Overview

Systematically audit CLAUDE.md and README.md against the live codebase, then apply targeted edits so both files accurately reflect reality. CLAUDE.md is for AI agents (terse, precise, command-focused); README.md is for humans (explanatory, narrative, onboarding-focused). Both must stay consistent with each other and with the code.

## When to Use

- User asks to "update CLAUDE.md" or "update README.md"
- User says docs are stale or out of sync
- After a major refactor or feature merge
- After adding/removing modules, scripts, or CLI commands
- When test counts or directory structures have changed

## Core Principle

**Docs describe what IS, not what WAS.** Every claim in the docs must be verifiable against the current codebase. If the code changed, the docs change. No nostalgia.

## Audit Workflow

Execute these phases in order. Phase 1 is read-only discovery — do NOT edit anything until Phase 2.

### Phase 1: Full-Project Scan (Read-Only)

Run these scans in parallel where possible. Build a fact table before comparing to docs.

**1a. Project structure**
```
find src -type f -name "*.py" | sort
find scripts -type f -name "*.py" | sort
find tests -type f -name "*.py" | sort
ls config/
ls docs/ 2>/dev/null
```

**1b. Key classes and their locations**
```
grep -rn "^class " src/ --include="*.py" | grep -v __pycache__
```
Cross-reference every class mentioned in docs — does the file path still match?

**1c. CLI entry points**
Read `run.py` and every `run_*.py`. Extract every subcommand, flag, and argument. Compare against documented commands in both files.

**1d. Test count (exact)**
```
python -m pytest tests/ --collect-only -q 2>/dev/null | tail -1
```
The CLAUDE.md test count must match this number exactly.

**1e. Config files**
List every file under `config/` and verify the config structure section in docs lists them all.

**1f. Standalone scripts**
List every `.py` file in `scripts/` that has a `main()` or `if __name__ == "__main__"` block. Any undocumented script is a gap.

**1g. Recent git changes**
```
git log --oneline -15
```
Look for features, renames, or refactors mentioned in commit messages that haven't reached the docs.

### Phase 2: Gap Analysis

Compare Phase 1 findings against both CLAUDE.md and README.md. Produce a structured gap report:

| Category | What's Wrong | File(s) Affected | Action |
|----------|-------------|------------------|--------|
| Stale data | Test count says 150, actual is 166 | CLAUDE.md | Update number |
| Missing module | `src/sniper/` not in layer stack | CLAUDE.md | Add to architecture |
| New command | `--llm` flag exists but undocumented | Both | Add to commands |
| Deleted file | Referenced file no longer exists | README.md | Remove reference |
| New class | `ConfluenceEngine` not mentioned | README.md | Add if significant |

**Checklist for every claim in docs:**
- [ ] File paths exist at the stated location
- [ ] Class names match exactly (case-sensitive)
- [ ] Command examples are runnable as written
- [ ] Numbers (test counts, thresholds, defaults) are current
- [ ] Architecture layer stack lists all major directories under `src/`
- [ ] Config section lists all files in `config/`
- [ ] Scripts section covers all standalone scripts

### Phase 3: Apply Updates

Apply edits in this order:

1. **CLAUDE.md first** — it's the source of truth for AI agents. Changes here inform the README.
2. **README.md second** — mirror structural changes from CLAUDE.md, but in human-friendly prose.

**Rules for CLAUDE.md edits:**
- Commands section: verify every example actually runs. Update flags, paths, and commentary.
- Architecture layer stack: every `src/<package>/` with `__init__.py` must appear. List the key classes inside.
- Config section: list every file in `config/` with its purpose.
- Key invariants: only list things that would break the system if violated.
- Keep it terse — this file is for AI consumption.

**Rules for README.md edits:**
- Add new sections for major features not yet documented.
- Remove or condense sections about deleted/deprecated features.
- Update all command examples to match current CLI.
- Architecture diagram: update if directory structure changed.
- Keep the narrative flow — this is for human onboarding.

**Rules for both files:**
- Never duplicate large blocks verbatim between the two files. CLAUDE.md is terse reference; README.md is explanatory prose.
- When adding a new section, add it to the right file: operational details → CLAUDE.md, conceptual explanations → README.md.
- Delete stale content — don't comment it out or append "TODO: update this".

### Phase 4: Consistency Check

After editing both files, verify cross-file consistency:

- [ ] Same test count in both files
- [ ] Same command examples (format may differ, content must match)
- [ ] Same architecture layer list (CLAUDE.md: one-line summary, README.md: expanded)
- [ ] Same config file list
- [ ] Same provider/adapter list
- [ ] No section in CLAUDE.md that contradicts README.md (or vice versa)

## What NOT to Do

- Do NOT add a "last updated" timestamp — git history tracks this.
- Do NOT add fluff like "this document describes..." intros.
- Do NOT duplicate the full README architecture into CLAUDE.md.
- Do NOT remove content just because it's "too detailed" — verify it's actually wrong first.
- Do NOT guess numbers, paths, or class names — look them up.

## Example: Test Count Update

**Trigger:** `python -m pytest tests/ --collect-only -q` returns `166 tests collected`.

**Action in CLAUDE.md:**
```diff
- # Run all tests (150 tests)
+ # Run all tests (166 tests)
```

**Action in README.md:**
Find and update any mention of the test count. If README.md doesn't mention a specific count, no change needed — README.md doesn't need to state the count, only CLAUDE.md does.

## Reference: Document Division of Labor

| Content | CLAUDE.md | README.md |
|---------|-----------|-----------|
| CLI commands with flags | Yes (terse) | Yes (with explanations) |
| Architecture layer stack | Yes (one-liners) | Yes (with descriptions) |
| Test counts | Yes (exact) | Optional |
| Config file listing | Yes | Yes |
| Key invariants | Yes | No |
| Installation/setup | No | Yes |
| Conceptual explanations | No | Yes |
| Diagrams (mermaid) | No | Yes |
| Agent-specific instructions | Yes | No |
| Code style preferences | Yes | No |
