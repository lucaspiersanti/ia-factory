"""Test helper: fake `gh` and `osascript` executables prepended to PATH.

Each fake call appends {"argv", "stdin", "cwd"} as one JSON line to a log.
Canned answers come from rules: the first rule whose "match" list is a
prefix of argv decides stdout, stderr and exit code (default: exit 0, no output).
A list "stdout" answers the Nth matching call with item N (the last item repeats).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

FAKE = """#!{python}
import json, os, sys
argv = [os.path.basename(sys.argv[0])] + sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({{"argv": argv, "stdin": sys.stdin.read(), "cwd": os.getcwd()}}) + "\\n")
for rule in json.loads(os.environ["FAKE_RULES"]):
    match = rule["match"]
    if argv[:len(match)] == match:
        out = rule.get("stdout", "")
        if isinstance(out, list):
            with open(os.environ["FAKE_LOG"]) as log:
                seen = sum(json.loads(line)["argv"][:len(match)] == match for line in log)
            out = out[min(seen, len(out)) - 1]
        sys.stdout.write(out)
        sys.stderr.write(rule.get("stderr", ""))
        sys.exit(rule.get("exit", 0))
"""


class FakeBin:
    def __init__(self, rules=()):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.log = root / "calls.jsonl"
        self.log.touch()
        bindir = root / "bin"
        bindir.mkdir()
        for name in ("gh", "osascript"):
            script = bindir / name
            script.write_text(FAKE.format(python=sys.executable))
            script.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_LOG": str(self.log),
            "FAKE_RULES": json.dumps(list(rules)),
        }

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def argvs(self):
        return [c["argv"] for c in self.calls()]

    def cleanup(self):
        self._tmp.cleanup()
