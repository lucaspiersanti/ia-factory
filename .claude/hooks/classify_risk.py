"""Stage F risk classifier (ADR-003).

stdin:  {"changed_files": [...], "repo_root": "<optional path>"}
        changed_files should come from `git diff --name-only --no-renames`
        so a rename reports both the old and the new path.
stdout: "fast" or "slow"
exit:   0 = fast path (auto-merge allowed), 2 = slow path (reason on stderr).

Fails closed: any error, unknown path or malformed input means slow.
"""
import json
import sys
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

DEFAULT_ALLOWLIST = [
    "*.md",
    "*.css",
    "locales/*", "*/locales/*",
    "i18n/*", "*/i18n/*",
]

# Always slow, even if a repo allowlist matches them. Compared lowercase.
ALWAYS_SLOW_DIRS = (".github/", ".claude/", ".factory/")
ALWAYS_SLOW_FILES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock", "uv.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock",
    "gemfile", "gemfile.lock", "composer.json", "composer.lock",
}

REPO_CONFIG = ".factory/risk.json"


def _is_unsafe(path):
    p = PurePosixPath(path)
    # Non-normalized paths ("./x", "a//b") could dodge the prefix checks.
    return not path or p.is_absolute() or ".." in p.parts or str(p) != path


def _is_always_slow(path):
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    return (low.startswith(ALWAYS_SLOW_DIRS)
            or name in ALWAYS_SLOW_FILES
            or (name.startswith("requirements") and name.endswith(".txt")))


def classify(changed_files, extra=()):
    if not changed_files:
        return "slow", "empty diff"
    allowlist = DEFAULT_ALLOWLIST + list(extra)
    for f in changed_files:
        if _is_unsafe(f):
            return "slow", f"unsafe path: {f!r}"
        if _is_always_slow(f):
            return "slow", f"protected path: {f}"
        if not any(fnmatchcase(f, pattern) for pattern in allowlist):
            return "slow", f"not in allowlist: {f}"
    return "fast", "all files in allowlist"


def _string_list(value, field):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def parse_extra(text):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{REPO_CONFIG} must be a JSON object")
    return _string_list(data.get("allowlist", []), "allowlist")


def load_extra(repo_root):
    if repo_root is None:
        return []
    config = Path(repo_root) / REPO_CONFIG
    if not config.exists():
        return []
    return parse_extra(config.read_text())


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("input must be a JSON object")
        files = _string_list(payload.get("changed_files"), "changed_files")
        path, reason = classify(files, load_extra(payload.get("repo_root")))
    except Exception as e:  # fail closed on anything unexpected
        path, reason = "slow", f"classifier error: {e}"
    print(path)
    if path == "slow":
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
