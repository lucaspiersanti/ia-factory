import json
import subprocess
import sys
import unittest
from pathlib import Path

from fake_bin import FakeBin

HOOK = Path(__file__).with_name("merge_gate.py")
REPO = "octo/app"
SHA, SHA2 = "a" * 40, "b" * 40
VIEW_CALL = ["gh", "pr", "view", "7", "--repo", REPO, "--json", "state,headRefOid,baseRefName"]
FILES_CALL = ["gh", "api", "repos/octo/app/pulls/7/files", "--paginate"]
RISK_CALL = ["gh", "api", "repos/octo/app/contents/.factory/risk.json?ref=main",
             "-H", "Accept: application/vnd.github.raw"]
MERGE_CALL = ["gh", "pr", "merge", "7", "--repo", REPO, "--merge", "--match-head-commit", SHA]
LABEL_CALL = ["gh", "pr", "edit", "7", "--repo", REPO, "--add-label", "needs-human-review"]
RISK_404 = {"match": RISK_CALL, "stderr": "gh: Not Found (HTTP 404)", "exit": 1}


def view(state="OPEN", heads=(SHA,)):
    return {"match": VIEW_CALL, "stdout": [
        json.dumps({"state": state, "headRefOid": h, "baseRefName": "main"}) for h in heads]}


def entry(f):
    if isinstance(f, tuple):  # (old, new) rename
        return {"filename": f[1], "previous_filename": f[0], "status": "renamed"}
    return {"filename": f, "status": "modified"}


def files(*pages):
    # gh --paginate concatenates one raw JSON array per page.
    return {"match": FILES_CALL, "stdout": "".join(json.dumps([entry(f) for f in p]) for p in pages)}


def merges(fake):
    return [a for a in fake.argvs() if a[:3] == ["gh", "pr", "merge"]]


class MergeGateTest(unittest.TestCase):
    def gate(self, rules, payload=None, **extra):
        fake = FakeBin(list(rules) + [view(), RISK_404])
        self.addCleanup(fake.cleanup)
        if payload is None:
            payload = {"repo": REPO, "pr": 7, **extra}
        data = payload if isinstance(payload, str) else json.dumps(payload)
        r = subprocess.run([sys.executable, str(HOOK)], input=data,
                           capture_output=True, text=True, env=fake.env)
        return r, fake

    def assertSlow(self, r, reason):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "slow")
        self.assertIn(reason, r.stderr)

    def test_fast_path_merges_pinned_head_on_explicit_repo(self):
        r, fake = self.gate([files(["README.md"], [("docs/old.md", "docs/new.md")])])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "merged")
        argvs = fake.argvs()
        self.assertEqual(merges(fake), [MERGE_CALL])
        self.assertIn(FILES_CALL, argvs)
        self.assertIn(RISK_CALL, argvs)
        for argv in argvs:
            with self.subTest(argv=argv):
                self.assertNotIn("--delete-branch", argv)
                self.assertNotIn("--jq", argv)
                self.assertFalse(any("{owner}" in a for a in argv))
                self.assertTrue(REPO in argv or any(a.startswith("repos/octo/app/") for a in argv))

    def test_rename_out_of_code_is_slow(self):
        r, fake = self.gate([files(["README.md"], [("src/x.py", "docs/x.md")])])
        self.assertSlow(r, "src/x.py")
        self.assertEqual(merges(fake), [])

    def test_unknown_path_is_labeled_and_notified(self):
        r, fake = self.gate([files(["src/app.py"])])
        self.assertSlow(r, "not in allowlist: src/app.py")
        argvs = fake.argvs()
        self.assertIn(LABEL_CALL, argvs)
        notify = [a for a in argvs if a[0] == "osascript"]
        self.assertEqual(len(notify), 1)
        self.assertIn("not in allowlist: src/app.py", notify[0])
        self.assertIn("ia-factory: PR #7 needs review", notify[0])
        self.assertEqual(merges(fake), [])

    def test_listing_failure_is_slow_without_merge(self):
        r, fake = self.gate([{"match": FILES_CALL, "stderr": "HTTP 502", "exit": 1}])
        self.assertSlow(r, "HTTP 502")
        self.assertIn("merge gate error", r.stderr)
        self.assertEqual(merges(fake), [])
        self.assertIn(LABEL_CALL, fake.argvs())

    def test_malformed_files_json_is_slow(self):
        for raw in ['{"filename": "a.md"}', "[1]", '[{"name": "a.md"}]',
                    '[{"filename": "a.md"}', '[{"filename": 3}]',
                    '[{"filename": "a.md", "previous_filename": 3}]', "[] junk"]:
            with self.subTest(raw=raw):
                r, fake = self.gate([{"match": FILES_CALL, "stdout": raw}])
                self.assertSlow(r, "merge gate error")
                self.assertEqual(merges(fake), [])

    def test_head_moved_during_classification_is_slow(self):
        r, fake = self.gate([view(heads=(SHA, SHA2)), files(["README.md"])])
        self.assertSlow(r, "head moved during classification")
        self.assertEqual(merges(fake), [])

    def test_bad_view_is_slow(self):
        for rule in [view(heads=("",)), view(heads=("not-a-sha",)),
                     {"match": VIEW_CALL, "stdout": "[]"}]:
            with self.subTest(rule=rule):
                r, fake = self.gate([rule, files(["README.md"])])
                self.assertSlow(r, "merge gate error")
                self.assertEqual(merges(fake), [])

    def test_closed_or_merged_pr_is_slow(self):
        for state in ["MERGED", "CLOSED"]:
            with self.subTest(state=state):
                r, fake = self.gate([view(state=state), files(["README.md"])])
                self.assertSlow(r, state)
                self.assertEqual(merges(fake), [])

    def test_base_branch_allowlist_extension_applies(self):
        risk = {"match": RISK_CALL, "stdout": '{"allowlist": ["assets/*.svg"]}'}
        r, _ = self.gate([risk, files(["assets/logo.svg"])])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_base_risk_json_uses_defaults(self):
        r, _ = self.gate([files(["assets/logo.svg"])])
        self.assertSlow(r, "not in allowlist: assets/logo.svg")

    def test_risk_json_read_failure_or_garbage_is_slow(self):
        for rule in [{"match": RISK_CALL, "stderr": "gh: Server Error (HTTP 500)", "exit": 1},
                     {"match": RISK_CALL, "stdout": '{"allowlist": "*"}'},
                     {"match": RISK_CALL, "stdout": "{oops"}]:
            with self.subTest(rule=rule):
                r, fake = self.gate([rule, files(["README.md"])])
                self.assertSlow(r, "merge gate error")
                self.assertEqual(merges(fake), [])

    def test_merge_failure_is_slow_and_labeled(self):
        rules = [files(["README.md"]),
                 {"match": ["gh", "pr", "merge"], "stderr": "head changed", "exit": 1}]
        r, fake = self.gate(rules)
        self.assertSlow(r, "head changed")
        self.assertIn(LABEL_CALL, fake.argvs())

    def test_label_and_notify_failures_keep_outcome(self):
        rules = [files(["src/app.py"]),
                 {"match": ["gh", "pr", "edit"], "stderr": "no label perms", "exit": 1},
                 {"match": ["osascript"], "stderr": "no gui", "exit": 1}]
        r, _ = self.gate(rules)
        self.assertSlow(r, "not in allowlist: src/app.py")
        self.assertIn("no label perms", r.stderr)
        self.assertIn("no gui", r.stderr)

    def test_dry_run_never_mutates(self):
        for paths, code, would in [
                (["README.md"], 0, f"gh pr merge 7 --repo {REPO} --merge --match-head-commit {SHA}"),
                (["src/app.py"], 2, f"gh pr edit 7 --repo {REPO} --add-label needs-human-review")]:
            with self.subTest(paths=paths):
                r, fake = self.gate([files(paths)], dry_run=True)
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertIn(f"would run: {would}", r.stdout)
                self.assertTrue(all(a[:3] in (["gh", "pr", "view"], ["gh", "api", a[2]])
                                    for a in fake.argvs()), fake.argvs())
                self.assertEqual(merges(fake), [])

    def test_api_file_cap_is_slow(self):
        r, fake = self.gate([files([f"docs/f{i}.md" for i in range(3000)])])
        self.assertSlow(r, "GitHub API cap")
        self.assertEqual(merges(fake), [])

    def test_invalid_input_is_slow_without_calls(self):
        for payload in ["not json", "[]", {"repo": REPO, "pr": 0}, {"repo": REPO, "pr": -1},
                        {"repo": REPO, "pr": True}, {"repo": REPO, "pr": "7"}, {"pr": 7},
                        {"pr": 7, "repo_dir": "."}, {"repo": "octo", "pr": 7},
                        {"repo": "octo/..", "pr": 7}, {"repo": "a;b/c", "pr": 7},
                        {"repo": REPO, "pr": 7, "dry_run": "yes"}]:
            with self.subTest(payload=payload):
                r, fake = self.gate([], payload=payload)
                self.assertSlow(r, "merge gate error")
                self.assertEqual(fake.calls(), [])


if __name__ == "__main__":
    unittest.main()
