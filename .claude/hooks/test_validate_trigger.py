import json
import subprocess
import sys
import unittest
from pathlib import Path

from validate_trigger import validate

HOOK = Path(__file__).with_name("validate_trigger.py")

VALID = {
    "id_tarea": "GH-142",
    "origen": "github",
    "prioridad": "high",
    "descripcion": "Login button overlaps footer on mobile",
}


def with_(**changes):
    return {**VALID, **changes}


class ValidateTest(unittest.TestCase):
    def test_valid_trigger_passes(self):
        self.assertIsNone(validate(VALID))

    def test_each_origin_is_accepted(self):
        for origen in ["sentry", "github", "slack"]:
            with self.subTest(origen=origen):
                self.assertIsNone(validate(with_(origen=origen)))

    def test_missing_field_fails(self):
        for field in VALID:
            with self.subTest(field=field):
                payload = {k: v for k, v in VALID.items() if k != field}
                self.assertIn(field, validate(payload))

    def test_unknown_field_fails(self):
        self.assertIn("extra", validate(with_(extra=1)))

    def test_bad_values_fail(self):
        cases = {
            "id_tarea": ["", "../etc", "a b", "-flag", "x" * 65, 42],
            "origen": ["jira", "GitHub", None, ["github"]],
            "prioridad": ["urgent", "", 1, {"high": 1}],
            "descripcion": ["", "   ", "x" * 10_001, ["list"]],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertIn(field, validate(with_(**{field: value})))

    def test_non_object_fails(self):
        self.assertIsNotNone(validate(["not", "an", "object"]))


class HookContractTest(unittest.TestCase):
    def run_hook(self, data):
        return subprocess.run([sys.executable, str(HOOK)], input=data,
                              capture_output=True, text=True)

    def test_valid_exits_0(self):
        r = self.run_hook(json.dumps(VALID))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_invalid_exits_2_with_reason(self):
        r = self.run_hook(json.dumps(with_(origen="jira")))
        self.assertEqual(r.returncode, 2)
        self.assertIn("origen", r.stderr)

    def test_malformed_json_exits_2(self):
        r = self.run_hook("{oops")
        self.assertEqual(r.returncode, 2)
        self.assertIn("validator error", r.stderr)


if __name__ == "__main__":
    unittest.main()
