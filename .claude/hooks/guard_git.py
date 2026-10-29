"""Stage C builder guard: Claude Code PreToolUse hook for the Bash tool.

Blocks, with exit 2 and the reason on stderr:
- pushes that target a protected branch (explicitly, via HEAD, or implicitly
  from a protected branch), deletions of it, and force/--all/--mirror pushes
- history changes (commit, merge, rebase, ...) while on a protected branch
  or on an unknown branch

This is a guardrail for an honest agent, not a sandbox: `sh -c`, `eval` or
scripts can bypass it. Server-side branch protection on GitHub is the real
enforcement. Fails closed on malformed input or unparseable git commands.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

PROTECTED = {"main", "master"}
HISTORY_CHANGES = {"commit", "merge", "rebase", "cherry-pick", "revert", "am"}
BULK_PUSH_FLAGS = {"--all", "--mirror", "--delete"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


class Blocked(Exception):
    pass


def current_branch(cwd):
    r = subprocess.run(["git", "-C", str(cwd), "symbolic-ref", "--short", "-q", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def segments(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segment = []
    for token in lex:
        if set(token) <= set("();<>|&"):
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def check_push(args, branch):
    for arg in args:
        short_flags = arg[1:] if arg.startswith("-") and not arg.startswith("--") else ""
        if (arg in BULK_PUSH_FLAGS or arg.startswith("--force")
                or "f" in short_flags or "d" in short_flags):
            raise Blocked(f"push flag {arg} is not allowed")
    refspecs = [a for a in args if not a.startswith("-")][1:]  # first one is the remote
    for refspec in refspecs or ["HEAD"]:
        if refspec.startswith("+"):
            raise Blocked(f"force refspec {refspec} is not allowed")
        dest = refspec.split(":", 1)[-1].removeprefix("refs/heads/")
        if dest == "HEAD" and (branch is None or branch in PROTECTED):
            raise Blocked(f"implicit push from branch {branch or 'unknown'}")
        if dest in PROTECTED:
            raise Blocked(f"push to protected branch {dest}")


def check(command, cwd):
    try:
        parsed = list(segments(command))
    except ValueError as e:
        if "git" in command:
            raise Blocked(f"cannot parse git command: {e}")
        return
    for seg in parsed:
        if seg[0] == "cd" and len(seg) > 1:
            cwd = cwd / Path(seg[1]).expanduser()
            continue
        if seg[0] != "git":
            continue
        i = 1
        while i < len(seg) and seg[i].startswith("-"):
            if seg[i] in GIT_OPTIONS_WITH_VALUE and i + 1 < len(seg):
                if seg[i] == "-C":
                    cwd = cwd / seg[i + 1]
                i += 1
            i += 1
        if i == len(seg):
            continue
        sub, args = seg[i], seg[i + 1:]
        if sub == "push":
            check_push(args, current_branch(cwd))
        elif sub in HISTORY_CHANGES:
            branch = current_branch(cwd)
            if branch is None or branch in PROTECTED:
                raise Blocked(f"git {sub} on branch {branch or 'unknown'}; use a work branch")


def main():
    try:
        payload = json.load(sys.stdin)
        if payload["tool_name"] != "Bash":
            return 0
        check(payload["tool_input"]["command"], Path(payload["cwd"]))
        return 0
    except Blocked as e:
        reason = str(e)
    except Exception as e:  # fail closed
        reason = f"guard error: {e!r}"
    print(f"guard_git: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
