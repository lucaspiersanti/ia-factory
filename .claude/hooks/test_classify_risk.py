import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from classify_risk import classify

HOOK = Path(__file__).with_name("classify_risk.py")


def run_hook(payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)], input=data, capture_output=True, text=True
    )


class ClassifyTest(unittest.TestCase):
    def test_docs_and_styles_only_is_fast(self):
        path, _ = classify(["README.md", "docs/guide.md", "web/app.css"])
        self.assertEqual(path, "fast")

    def test_i18n_files_are_fast(self):
        path, _ = classify(["locales/es.json", "web/i18n/en.json"])
        self.assertEqual(path, "fast")

    def test_one_unknown_file_makes_it_slow(self):
        path, reason = classify(["README.md", "src/db/migrate.py"])
        self.assertEqual(path, "slow")
        self.assertIn("src/db/migrate.py", reason)

    def test_empty_diff_is_slow(self):
        self.assertEqual(classify([])[0], "slow")

    def test_hard_overrides_beat_allowlist(self):
        for f in [".github/workflows/ci.md", ".claude/agents/x.md",
                  ".factory/risk.json", "package.json", "web/yarn.lock",
                  "poetry.lock", ".GitHub/notes.md"]:
            with self.subTest(f=f):
                self.assertEqual(classify([f], extra=["*"])[0], "slow")

    def test_unsafe_paths_are_slow(self):
        for f in ["../outside.md", "/etc/notes.md", "", "./.claude/x.md",
                  ".github//ci.md", "docs/./a.md"]:
            with self.subTest(f=f):
                self.assertEqual(classify([f])[0], "slow")

    def test_repo_allowlist_extends_default(self):
        self.assertEqual(classify(["assets/logo.svg"])[0], "slow")
        self.assertEqual(classify(["assets/logo.svg"], extra=["assets/*.svg"])[0], "fast")


class HookContractTest(unittest.TestCase):
    def test_fast_exits_0(self):
        r = run_hook({"changed_files": ["README.md"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "fast")

    def test_slow_exits_2_with_reason(self):
        r = run_hook({"changed_files": ["src/app.py"]})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout.strip(), "slow")
        self.assertIn("src/app.py", r.stderr)

    def test_malformed_input_is_slow(self):
        for payload in ["not json", "[]", {"changed_files": "README.md"},
                        {"changed_files": [1]}, {}]:
            with self.subTest(payload=payload):
                r = run_hook(payload)
                self.assertEqual(r.returncode, 2)
                self.assertIn("classifier error", r.stderr)

    def test_repo_config_extends_allowlist(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / ".factory").mkdir()
            (Path(root) / ".factory/risk.json").write_text('{"allowlist": ["assets/*.svg"]}')
            r = run_hook({"changed_files": ["assets/logo.svg"], "repo_root": root})
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_repo_config_uses_default(self):
        with tempfile.TemporaryDirectory() as root:
            r = run_hook({"changed_files": ["README.md"], "repo_root": root})
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_broken_repo_config_is_slow(self):
        for content in ["{oops", '{"allowlist": "*.svg"}', '{"allowlist": [1]}']:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as root:
                (Path(root) / ".factory").mkdir()
                (Path(root) / ".factory/risk.json").write_text(content)
                r = run_hook({"changed_files": ["README.md"], "repo_root": root})
                self.assertEqual(r.returncode, 2)
                self.assertIn("classifier error", r.stderr)


if __name__ == "__main__":
    unittest.main()
