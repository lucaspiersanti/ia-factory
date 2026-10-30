import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fake_bin import FakeBin

HOOK = Path(__file__).with_name("onboard_repo.py")
PROTECTION = "repos/octo/app/branches/main/protection"
VIEW = {"match": ["gh", "repo", "view"], "stdout": "main\n"}
GOOD = {
    "enforce_admins": {"enabled": True},
    "required_pull_request_reviews": {"required_approving_review_count": 0},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
}


def readback(protection):
    return {"match": ["gh", "api", PROTECTION], "stdout": json.dumps(protection)}


def git_clone_stub(path, origin):
    """A real local git repo with the given origin URL (no network)."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)


class OnboardRepoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = tmp.name

    def onboard(self, rules, payload=None, **extra):
        fake = FakeBin(rules)
        self.addCleanup(fake.cleanup)
        if payload is None:
            payload = {"repo": "octo/app", "workspaces_dir": self.ws, **extra}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, env=fake.env)
        return r, fake

    def test_happy_path_order_and_body(self):
        r, fake = self.onboard([VIEW, readback(GOOD)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "onboarded octo/app")
        argvs = fake.argvs()
        self.assertEqual(argvs, [
            ["gh", "repo", "clone", "octo/app", str(Path(self.ws) / "app")],
            ["gh", "repo", "view", "octo/app", "--json", "defaultBranchRef",
             "-q", ".defaultBranchRef.name"],
            ["gh", "api", "-X", "PUT", PROTECTION, "--input", "-"],
            ["gh", "label", "create", "needs-human-review", "--repo", "octo/app",
             "--color", "B60205", "--force"],
            ["gh", "repo", "edit", "octo/app", "--delete-branch-on-merge"],
            ["gh", "api", PROTECTION],
        ])
        self.assertEqual(json.loads(fake.calls()[2]["stdin"]), {
            "required_status_checks": None,
            "enforce_admins": True,
            "required_pull_request_reviews": {"required_approving_review_count": 0},
            "restrictions": None,
            "allow_force_pushes": False,
            "allow_deletions": False,
        })

    def test_protection_failure_hints_free_plan(self):
        put = {"match": ["gh", "api", "-X", "PUT"], "stderr": "HTTP 403", "exit": 1}
        r, fake = self.onboard([VIEW, put, readback(GOOD)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("GitHub Free only protects public repos", r.stderr)
        self.assertNotIn("label", [a[1] for a in fake.argvs()])

    def test_readback_mismatch_fails(self):
        for key, bad in [("allow_force_pushes", {"enabled": True}),
                         ("enforce_admins", {"enabled": False}),
                         ("allow_deletions", {"enabled": True}),
                         ("required_pull_request_reviews", None)]:
            with self.subTest(key=key):
                protection = {**GOOD, key: bad}
                if bad is None:
                    del protection[key]
                r, _ = self.onboard([VIEW, readback(protection)])
                self.assertEqual(r.returncode, 2)
                self.assertIn("protection read-back does not match", r.stderr)

    def test_existing_clone_of_same_repo_is_not_recloned(self):
        for origin in ["https://github.com/Octo/App.git", "git@github.com:octo/app",
                       "https://github.com/octo/app"]:
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as ws:
                git_clone_stub(Path(ws) / "app", origin)
                r, fake = self.onboard([VIEW, readback(GOOD)],
                                       payload={"repo": "octo/app", "workspaces_dir": ws})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("clone", [a[2] for a in fake.argvs()])

    def test_existing_dir_that_is_not_this_clone_fails(self):
        cases = {
            "empty dir": None,
            "other owner": "https://github.com/other/app.git",
            "lookalike host": "https://github.com.evil.io/octo/app.git",
            "suffix trick": "https://github.com/octo/app-fork.git",
        }
        for label, origin in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as ws:
                target = Path(ws) / "app"
                if origin is None:
                    target.mkdir()
                else:
                    git_clone_stub(target, origin)
                r, fake = self.onboard([VIEW, readback(GOOD)],
                                       payload={"repo": "octo/app", "workspaces_dir": ws})
                self.assertEqual(r.returncode, 2)
                self.assertIn("is not a clone of octo/app", r.stderr)
                self.assertEqual(fake.calls(), [])

    def test_plain_dir_inside_a_matching_repo_fails(self):
        # workspaces/ may live inside a git repo; its origin must not vouch for app/.
        git_clone_stub(Path(self.ws), "https://github.com/octo/app.git")
        (Path(self.ws) / "app").mkdir()
        r, fake = self.onboard([VIEW, readback(GOOD)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not a clone of octo/app", r.stderr)
        self.assertEqual(fake.calls(), [])

    def test_invalid_input_makes_no_calls(self):
        for payload in [{"repo": "octo", "workspaces_dir": self.ws},
                        {"repo": "octo/..", "workspaces_dir": self.ws},
                        {"repo": "octo/.", "workspaces_dir": self.ws},
                        {"repo": "../x", "workspaces_dir": self.ws},
                        {"repo": "octo/app/x", "workspaces_dir": self.ws},
                        {"repo": "oc to/app", "workspaces_dir": self.ws},
                        {"repo": "octo/a;b", "workspaces_dir": self.ws},
                        {"repo": 123, "workspaces_dir": self.ws},
                        {"repo": "octo/app"},
                        {"repo": "octo/app", "workspaces_dir": self.ws + "/nope"},
                        {"repo": "octo/app", "workspaces_dir": self.ws, "dry_run": 1},
                        []]:
            with self.subTest(payload=payload):
                r, fake = self.onboard([], payload=payload)
                self.assertEqual(r.returncode, 2)
                self.assertIn("onboarding error", r.stderr)
                self.assertEqual(fake.calls(), [])

    def test_dry_run_makes_no_mutating_calls(self):
        r, fake = self.onboard([VIEW], dry_run=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([a[:3] for a in fake.argvs()], [["gh", "repo", "view"]])
        for would in ["gh repo clone octo/app", f"gh api -X PUT {PROTECTION}",
                      "gh label create needs-human-review",
                      "gh repo edit octo/app --delete-branch-on-merge"]:
            self.assertIn(f"would run: {would}", r.stdout)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "onboarded octo/app")


if __name__ == "__main__":
    unittest.main()
