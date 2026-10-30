"""Target repo onboarding (ADR-004, T6).

stdin:  {"repo": "owner/name", "workspaces_dir": "<path>", "dry_run": <bool, optional>}
stdout: "onboarded owner/name"; in dry run, preceded by "would run: ..." lines.
exit:   0 = cloned (or already present), protected and labeled; 2 = error (reason on stderr).

Clones into <workspaces_dir>/<name>, protects the default branch like ia-factory's
main (T6) and creates the needs-human-review label used by the merge gate.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from merge_gate import LABEL, act, run, valid_repo

ORIGIN_RE = re.compile(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?$")
# 0 approvals: a solo owner cannot approve their own PR.
PROTECTION = {
    "required_status_checks": None,
    "enforce_admins": True,
    "required_pull_request_reviews": {"required_approving_review_count": 0},
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def parse(payload):
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    repo, ws = payload.get("repo"), payload.get("workspaces_dir")
    dry_run = payload.get("dry_run", False)
    if not valid_repo(repo):
        raise ValueError(f"invalid repo: {repo!r}")
    if not isinstance(ws, str) or not ws or not Path(ws).is_dir():
        raise ValueError("workspaces_dir must be an existing directory")
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    return repo, ws, dry_run


def verify(p):
    ok = (p["enforce_admins"]["enabled"] is True
          and "required_pull_request_reviews" in p
          and p["allow_force_pushes"]["enabled"] is False
          and p["allow_deletions"]["enabled"] is False)
    if not ok:
        raise ValueError("protection read-back does not match")


def check_clone(target, repo):
    """An existing target must be the root of a clone of exactly this repo."""
    problem = None
    try:
        top = run(["git", "-C", str(target), "rev-parse", "--show-toplevel"]).strip()
        origin = run(["git", "-C", str(target), "remote", "get-url", "origin"]).strip()
    except Exception as e:
        problem = str(e)
    else:
        m = ORIGIN_RE.match(origin)
        if Path(top).resolve() != target.resolve():
            problem = f"it lies inside the git repo at {top}"
        elif not m or m.group(1).lower() != repo.lower():
            problem = f"origin is {origin!r}"
    if problem:
        raise ValueError(f"{target} exists but is not a clone of {repo}: {problem}")


def onboard(repo, ws, dry_run):
    target = Path(ws) / repo.split("/")[1]
    if target.exists():
        check_clone(target, repo)
    else:
        act(["gh", "repo", "clone", repo, str(target)], dry_run)
    branch = run(["gh", "repo", "view", repo, "--json", "defaultBranchRef",
                  "-q", ".defaultBranchRef.name"]).strip()
    if not branch:
        raise ValueError("empty default branch")
    protection = f"repos/{repo}/branches/{quote(branch, safe='')}/protection"
    try:
        act(["gh", "api", "-X", "PUT", protection, "--input", "-"], dry_run,
            stdin=json.dumps(PROTECTION))
    except Exception as e:
        raise RuntimeError(f"{e} (GitHub Free only protects public repos)")
    act(["gh", "label", "create", LABEL, "--repo", repo, "--color", "B60205", "--force"], dry_run)
    # The merge gate merges without --delete-branch; GitHub deletes the head branch.
    act(["gh", "repo", "edit", repo, "--delete-branch-on-merge"], dry_run)
    if not dry_run:  # nothing was applied in dry run, so nothing to read back
        try:
            verify(json.loads(run(["gh", "api", protection])))
        except (KeyError, TypeError) as e:
            raise ValueError(f"protection read-back does not match: missing {e}")


def main():
    try:
        repo, ws, dry_run = parse(json.load(sys.stdin))
        onboard(repo, ws, dry_run)
    except Exception as e:  # fail closed
        print(f"onboarding error: {e}", file=sys.stderr)
        return 2
    print(f"onboarded {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
