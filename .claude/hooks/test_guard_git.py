import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("guard_git.py")


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


class GuardGitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def on_branch(self, name):
        git(self.repo, "checkout", "-q", "-b", name)

    def run_hook(self, command, tool="Bash", cwd=None):
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool,
                   "tool_input": {"command": command}, "cwd": cwd or self.repo}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True)

    def assertBlocked(self, command, **kw):
        r = self.run_hook(command, **kw)
        self.assertEqual(r.returncode, 2, f"not blocked: {command}")
        # Exit 2 alone would also match a crash; require our own message.
        self.assertIn("guard_git:", r.stderr)

    def assertAllowed(self, command, **kw):
        r = self.run_hook(command, **kw)
        self.assertEqual(r.returncode, 0, f"{command}: {r.stderr}")

    def test_push_to_protected_branch_is_blocked(self):
        self.on_branch("feat/x")
        for cmd in ["git push origin main", "git push origin HEAD:main",
                    "git push origin feat/x:refs/heads/main", "git push origin master",
                    "git push origin :main", "git push --delete origin main",
                    "git -C . push origin main", "cd . && git push origin main"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd)

    def test_force_and_bulk_push_are_blocked(self):
        self.on_branch("feat/x")
        for cmd in ["git push -f origin feat/x", "git push --force origin feat/x",
                    "git push --force-with-lease origin feat/x",
                    "git push origin +feat/x", "git push --all origin",
                    "git push --mirror origin"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd)

    def test_implicit_push_from_main_is_blocked(self):
        self.assertBlocked("git push")
        self.assertBlocked("git push origin")
        self.assertBlocked("git push origin HEAD")

    def test_history_changes_on_main_are_blocked(self):
        for cmd in ["git commit -m x", "git merge feat/x", "git rebase feat/x",
                    "git cherry-pick abc", "git revert abc", "git am p.patch"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd)

    def test_work_branch_operations_are_allowed(self):
        self.on_branch("feat/x")
        for cmd in ["git push -u origin feat/x", "git push origin HEAD",
                    "git push", "git commit -m 'feat: x'", "git status",
                    "echo main && git log --oneline", "ls -la"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)

    def test_read_only_git_on_main_is_allowed(self):
        for cmd in ["git status", "git log -1", "git diff", "git fetch origin",
                    "git checkout -b feat/y"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)

    def test_non_bash_tools_pass_through(self):
        self.assertAllowed("git push origin main", tool="Write")

    def test_unknown_branch_blocks_history_changes(self):
        with tempfile.TemporaryDirectory() as not_a_repo:
            self.assertBlocked("git commit -m x", cwd=not_a_repo)
            self.assertAllowed("ls", cwd=not_a_repo)

    def test_unparseable_git_command_is_blocked(self):
        self.assertBlocked("git push origin 'main")

    def test_malformed_input_is_blocked(self):
        for data in ["{oops", "[]", json.dumps({"tool_name": "Bash"})]:
            with self.subTest(data=data):
                r = subprocess.run([sys.executable, str(HOOK)], input=data,
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)
                self.assertIn("guard_git:", r.stderr)


if __name__ == "__main__":
    unittest.main()
