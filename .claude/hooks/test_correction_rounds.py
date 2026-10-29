import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("correction_rounds.py")


class CorrectionRoundsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def assertEscalates(self, result):
        # Exit 2 alone would also match a crash; require our own message.
        self.assertEqual(result.returncode, 2)
        self.assertIn("escalate to human", result.stderr)

    def request(self, id_tarea="GH-142", **overrides):
        payload = {"id_tarea": id_tarea, "state_dir": self.state_dir, **overrides}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True)

    def test_two_rounds_allowed_then_escalate(self):
        first, second, third = self.request(), self.request(), self.request()
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "round 1"))
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "round 2"))
        self.assertEscalates(third)

    def test_cap_stays_reached(self):
        for _ in range(3):
            self.request()
        self.assertEscalates(self.request())

    def test_tasks_have_separate_budgets(self):
        self.request("GH-1"), self.request("GH-1")
        self.assertEqual(self.request("GH-2").returncode, 0)

    def test_corrupt_counter_escalates(self):
        Path(self.state_dir, "GH-142.json").write_text("{oops")
        self.assertEscalates(self.request())

    def test_tampered_counter_escalates(self):
        for content in ['{"rounds": -5}', '{"rounds": "0"}', "[]"]:
            with self.subTest(content=content):
                Path(self.state_dir, "GH-142.json").write_text(content)
                self.assertEscalates(self.request())

    def test_unsafe_id_is_rejected(self):
        self.assertEscalates(self.request("../escape"))
        self.assertFalse(Path(self.state_dir).parent.joinpath("escape.json").exists())

    def test_missing_state_dir_is_rejected(self):
        r = subprocess.run([sys.executable, str(HOOK)],
                           input=json.dumps({"id_tarea": "GH-142"}),
                           capture_output=True, text=True)
        self.assertEscalates(r)

    def test_malformed_input_is_rejected(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="{oops",
                           capture_output=True, text=True)
        self.assertEscalates(r)


if __name__ == "__main__":
    unittest.main()
