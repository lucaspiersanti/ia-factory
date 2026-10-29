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
| 2 | `feat/hooks-trigger-rounds` | T3 | a71df38 | ~283 |
| 3 | `feat/hooks-builder-guard` | T4 | see Progress | ~250 |

PRs opened 2026-10-29 at the user's request: slice 1 = #1 (base `main`), slice 2 = #2 (base slice 1), slice 3 = #3 (base slice 2). After a parent merges, retarget the child to `main`.

Known `guard_git` false positive: a Bash command that contains "git" plus a heredoc with unbalanced quotes (e.g. an apostrophe) cannot be parsed and is blocked. Write such content with a file tool, then run the git/gh command on its own.

## Checklist
- [x] T1 Skeleton: `git init`, feature branch, `.gitignore`, this document. Route: inline (mechanical). Check: structural readback. Commit: see Progress.
- [x] T2 `classify_risk.py` with TDD (Stage F). Route: inline (one hook + its test, design already fixed by ADR-003). Check: `python3 -m unittest discover -s .claude/hooks` → 13 tests OK. RED observed twice (missing module; non-normalized path bypass), then GREEN.
- [x] T3 Trigger validation (Stage A) + correction-round counter (Stage E), with tests. Route: inline (two small hooks, design fixed by ADR-002). Check: `python3 -m unittest discover -s .claude/hooks` → 30 tests OK. RED observed (missing modules; unhashable list/dict values crashing `validate`), then GREEN.
- [x] T4 Builder guards (Stage C): `guard_git.py` PreToolUse hook on Bash, registered in `.claude/settings.json`. Route: inline (one hook + test + settings). Check: `python3 -m unittest discover -s .claude/hooks` → 40 tests OK; RED observed (39 failing subtests); live check in Claude Code: `git push origin main` blocked by the hook.
- [ ] T5 Stage A–F subagents and skills + end-to-end dry run with a sample trigger JSON. Target repos are cloned into `workspaces/` (ADR-004).
- [x] T6 GitHub branch protection on `main` for ia-factory: public repo `lucaspiersanti/ia-factory` (user chose public: Free plan only protects public repos), default branch `main`, PR required with 0 approvals (a solo owner cannot approve their own PR; Stage F auto-merge goes through a PR), `enforce_admins` on, force push and deletion off. The user pushed `main` themselves because `guard_git` blocks the agent. Check: protection read back from the GitHub API. Every target repo must get the same protection when it is onboarded (part of T5).

## Acceptance criteria
- Every hook has a `unittest` file next to it and all tests pass.
- Unknown input, errors, or missing config always resolve to block / slow path.
- One sample trigger runs A→F end to end in dry-run mode.

## Progress
- T1 done 2026-10-29. Directories under `.claude/` are created by the tasks that put files in them (no empty scaffolding).

- T2 done 2026-10-29. Contract: stdin `{"changed_files": [...], "repo_root"?}`, stdout `fast|slow`, exit 0 = fast, exit 2 = slow. Repo allowlist extension lives in `<repo>/.factory/risk.json` (`{"allowlist": [globs]}`); `.factory/` itself is protected so a PR cannot widen its own allowlist and self-merge. Callers must pass `git diff --name-only --no-renames`.

- T3 done 2026-10-29 on slice 2. `validate_trigger.py`: strict schema, `origen` in sentry|github|slack, `prioridad` in low|medium|high|critical (agent default, user may change), safe `id_tarea` charset (used as branch and state file name). `correction_rounds.py`: stdin `{"id_tarea", "state_dir"}`, grants round 1 and 2, then exit 2 "escalate to human"; corrupt/tampered counter escalates. Negative hook tests assert our own stderr message, because a missing or crashing hook also exits 2.

- T4 done 2026-10-29 on slice 3. Blocks: push to main/master (explicit, `HEAD:main`, `:main`, `--delete`, implicit from main), force/`+refspec`/`--all`/`--mirror`, and commit/merge/rebase/cherry-pick/revert/am on main/master or an unknown branch. Understands `cd x &&` and `git -C x`. Known limit: `sh -c`/`eval`/scripts bypass it; GitHub branch protection on `main` is the real enforcement. Open point for T5: these hooks fire only when Claude Code runs with ia-factory as project; the Builder working in a target repo clone needs them installed there too.

## Next step
T5: Stage A–F subagents and skills + end-to-end dry run, on a new slice branch stacked on slice 3.
