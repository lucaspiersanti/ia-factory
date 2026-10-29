# Feature: factory-bootstrap

## Objective
Build the ia-factory orchestrator on top of Claude Code: safety gates (hooks) first, then the stage agents and skills.

## Problem / Why
Development should not depend on a human as the bottleneck. The human approves exceptions (Stage F slow path) instead of executing every step.

## Scope
- Python 3 stdlib hooks in `.claude/hooks/` (ADR-001)
- Subagents in `.claude/agents/`, stage skills in `.claude/skills/`
- Target repos on GitHub via `gh` CLI

## Constraints
- Brain (Engram): `brain/architecture-stack`, `brain/coding-standards`, `brain/adr/001..003`, `brain/backlog`
- Fail closed: any hook error blocks (exit 2, reason on stderr)
- Stage E cap: 2 correction rounds (ADR-002)
- Stage F: path allowlist, unknown paths go to the slow path (ADR-003)
- Conventional Commits, no AI attribution

## Delivery strategy
`ask-on-risk`. Forecast: ~800 authored changed lines across all tasks, so the chain strategy question comes up before crossing ~400.

## Checklist
- [x] T1 Skeleton: `git init`, feature branch, `.gitignore`, this document. Route: inline (mechanical). Check: structural readback. Commit: see Progress.
- [x] T2 `classify_risk.py` with TDD (Stage F). Route: inline (one hook + its test, design already fixed by ADR-003). Check: `python3 -m unittest discover -s .claude/hooks` → 13 tests OK. RED observed twice (missing module; non-normalized path bypass), then GREEN.
- [ ] T3 Trigger validation (Stage A) + correction-round counter (Stage E), with tests.
- [ ] T4 Builder guards (Stage C): block push to `main` and writes outside the work branch.
- [ ] T5 Stage A–F subagents and skills + end-to-end dry run with a sample trigger JSON.

## Acceptance criteria
- Every hook has a `unittest` file next to it and all tests pass.
- Unknown input, errors, or missing config always resolve to block / slow path.
- One sample trigger runs A→F end to end in dry-run mode.

## Progress
- T1 done 2026-10-29. Directories under `.claude/` are created by the tasks that put files in them (no empty scaffolding).

- T2 done 2026-10-29. Contract: stdin `{"changed_files": [...], "repo_root"?}`, stdout `fast|slow`, exit 0 = fast, exit 2 = slow. Repo allowlist extension lives in `<repo>/.factory/risk.json` (`{"allowlist": [globs]}`); `.factory/` itself is protected so a PR cannot widen its own allowlist and self-merge. Callers must pass `git diff --name-only --no-renames`.

## Next step
T3: trigger validation (Stage A) + correction-round counter (Stage E).
