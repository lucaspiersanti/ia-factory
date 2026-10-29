"""Stage F merge gate (ADR-003, ADR-005).

stdin:  {"repo": "owner/name", "pr": <int>, "dry_run": <bool, optional>}
stdout: "merged" (fast path) or "slow"; in dry run, preceded by "would run: ..." lines.
exit:   0 = PR merged, 2 = slow path (reason on stderr). A slow PR is labeled
        needs-human-review and a macOS notification is sent, both best effort.

Everything is read from GitHub for the explicit repo; no local working tree is
trusted. The allowlist extension comes from the PR's base branch and the merge
is pinned to the head commit that was classified.
Fails closed: any error means slow and the PR is never merged.
"""
import json
import re
import shlex
import subprocess
import sys
from urllib.parse import quote

from classify_risk import REPO_CONFIG, classify, parse_extra

LABEL = "needs-human-review"
API_FILE_CAP = 3000  # GitHub lists at most 3000 files per PR
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
# Reason and title go through argv, so no AppleScript quoting is needed.
NOTIFY = ["-e", "on run argv",
          "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
          "-e", "end run"]


def valid_repo(repo):
    return (isinstance(repo, str) and bool(REPO_RE.match(repo))
            and repo.split("/")[1] not in (".", ".."))


def run(cmd, cwd=None, stdin=""):
    r = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{shlex.join(cmd[:3])} failed: {r.stderr.strip()}")
    return r.stdout


def act(cmd, dry_run, cwd=None, stdin=""):
    """Run a mutating command, or only print it in dry run."""
    if dry_run:
        print(f"would run: {shlex.join(cmd)}")
        return
    run(cmd, cwd, stdin)


def parse(payload):
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    repo, pr = payload.get("repo"), payload.get("pr")
    dry_run = payload.get("dry_run", False)
    if not valid_repo(repo):
        raise ValueError(f"invalid repo: {repo!r}")
    if type(pr) is not int or pr <= 0:
        raise ValueError("pr must be a positive integer")
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    return repo, pr, dry_run


def pr_view(repo, pr):
    info = json.loads(run(["gh", "pr", "view", str(pr), "--repo", repo,
                           "--json", "state,headRefOid,baseRefName"]))
    if not isinstance(info.get("state"), str) or not isinstance(info.get("baseRefName"), str):
        raise ValueError("unexpected gh pr view output")
    if not isinstance(info.get("headRefOid"), str) or not SHA_RE.match(info["headRefOid"]):
        raise ValueError(f"bad head sha: {info.get('headRefOid')!r}")
    return info


def parse_files(raw):
    """Decode `gh api --paginate` output: one JSON array per page, concatenated."""
    decoder, pos, files = json.JSONDecoder(), 0, []
    while True:
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos == len(raw):
            return files
        page, pos = decoder.raw_decode(raw, pos)
        if not isinstance(page, list):
            raise ValueError("files page is not a list")
        for f in page:
            if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
                raise ValueError(f"bad file entry: {f!r}")
            files.append(f["filename"])
            if "previous_filename" in f:  # a rename: classify the old path too
                if not isinstance(f["previous_filename"], str):
                    raise ValueError(f"bad file entry: {f!r}")
                files.append(f["previous_filename"])


def base_extra(repo, base):
    path = f"repos/{repo}/contents/{REPO_CONFIG}?ref={quote(base, safe='')}"
    try:
        text = run(["gh", "api", path, "-H", "Accept: application/vnd.github.raw"])
    except RuntimeError as e:
        if "HTTP 404" in str(e):  # no repo config on the base branch: defaults only
            return []
        raise
    return parse_extra(text)


def decide(repo, pr):
    """Return (path, reason, head sha that was classified)."""
    info = pr_view(repo, pr)
    head = info["headRefOid"]
    if info["state"] != "OPEN":
        return "slow", f"PR state is {info['state']}, not OPEN", head
    files = parse_files(run(["gh", "api", f"repos/{repo}/pulls/{pr}/files", "--paginate"]))
    if pr_view(repo, pr)["headRefOid"] != head:
        return "slow", "head moved during classification", head
    if len(files) >= API_FILE_CAP:
        return "slow", f"{len(files)} paths reach the GitHub API cap of {API_FILE_CAP}", head
    path, reason = classify(files, base_extra(repo, info["baseRefName"]))
    return path, reason, head


def escalate(repo, pr, reason, dry_run):
    for cmd in (["gh", "pr", "edit", str(pr), "--repo", repo, "--add-label", LABEL],
                ["osascript", *NOTIFY, reason, f"ia-factory: PR #{pr} needs review"]):
        try:
            act(cmd, dry_run)
        except Exception as e:  # best effort: never changes the outcome
            print(f"warning: {e}", file=sys.stderr)


def main():
    repo = pr = None
    dry_run = False
    try:
        repo, pr, dry_run = parse(json.load(sys.stdin))
        path, reason, head = decide(repo, pr)
        if path == "fast":
            # Branch deletion is a repo setting (onboard_repo), so a failed
            # delete can never turn a completed merge into "slow".
            act(["gh", "pr", "merge", str(pr), "--repo", repo, "--merge",
                 "--match-head-commit", head], dry_run)
            print("merged")
            return 0
    except Exception as e:  # fail closed: never merge on error
        reason = f"merge gate error: {e}"
    if pr is not None:
        escalate(repo, pr, reason, dry_run)
    print("slow")
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
