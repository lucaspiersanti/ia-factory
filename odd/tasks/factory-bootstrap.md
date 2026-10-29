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
`ask-on-risk`, chain strategy `stacked-to-main` (chosen 2026-10-29). Each slice is a branch whose PR targets `main`; a child PR targets its parent branch until the parent merges, then retargets to `main`.

| Slice | Branch | Tasks | Commits | Lines |
|---|---|---|---|---|
| 1 | `feat/hooks-risk-classifier` | T1, T2 | bd29bf9, 01cf5fa | ~240 |
| 2 | `feat/hooks-trigger-rounds` | T3 | see Progress | ~270 |

No git remote yet: pushing and opening PRs are the user's decision.

## Checklist
- [x] T1 Skeleton: `git init`, feature branch, `.gitignore`, this document. Route: inline (mechanical). Check: structural readback. Commit: see Progress.
- [x] T2 `classify_risk.py` with TDD (Stage F). Route: inline (one hook + its test, design already fixed by ADR-003). Check: `python3 -m unittest discover -s .claude/hooks` → 13 tests OK. RED observed twice (missing module; non-normalized path bypass), then GREEN.
- [x] T3 Trigger validation (Stage A) + correction-round counter (Stage E), with tests. Route: inline (two small hooks, design fixed by ADR-002). Check: `python3 -m unittest discover -s .claude/hooks` → 30 tests OK. RED observed (missing modules; unhashable list/dict values crashing `validate`), then GREEN.
- [ ] T4 Builder guards (Stage C): block push to `main` and writes outside the work branch.
- [ ] T5 Stage A–F subagents and skills + end-to-end dry run with a sample trigger JSON.

## Acceptance criteria
- Every hook has a `unittest` file next to it and all tests pass.
- Unknown input, errors, or missing config always resolve to block / slow path.
- One sample trigger runs A→F end to end in dry-run mode.

## Progress
- T1 done 2026-10-29. Directories under `.claude/` are created by the tasks that put files in them (no empty scaffolding).

- T2 done 2026-10-29. Contract: stdin `{"changed_files": [...], "repo_root"?}`, stdout `fast|slow`, exit 0 = fast, exit 2 = slow. Repo allowlist extension lives in `<repo>/.factory/risk.json` (`{"allowlist": [globs]}`); `.factory/` itself is protected so a PR cannot widen its own allowlist and self-merge. Callers must pass `git diff --name-only --no-renames`.

- T3 done 2026-10-29 on slice 2. `validate_trigger.py`: strict schema, `origen` in sentry|github|slack, `prioridad` in low|medium|high|critical (agent default, user may change), safe `id_tarea` charset (used as branch and state file name). `correction_rounds.py`: stdin `{"id_tarea", "state_dir"}`, grants round 1 and 2, then exit 2 "escalate to human"; corrupt/tampered counter escalates. Negative hook tests assert our own stderr message, because a missing or crashing hook also exits 2.

## Next step
T4: builder guards (Stage C), on a new slice branch stacked on slice 2.
