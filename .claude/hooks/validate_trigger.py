"""Stage A trigger validator.

stdin: {"id_tarea", "origen", "prioridad", "descripcion"}
exit:  0 = valid, 2 = invalid (reason on stderr).

id_tarea later becomes a branch name and a state file name, so it is
restricted to a safe charset. Unknown fields are rejected (fail closed).
"""
import json
import re
import sys

ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ORIGINS = {"sentry", "github", "slack"}
PRIORITIES = {"low", "medium", "high", "critical"}
MAX_DESCRIPTION = 10_000
FIELDS = {"id_tarea", "origen", "prioridad", "descripcion"}


def valid_id(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def validate(trigger):
    """Return None if valid, otherwise the reason."""
    if not isinstance(trigger, dict):
        return "trigger must be a JSON object"
    missing = FIELDS - trigger.keys()
    if missing:
        return f"missing fields: {', '.join(sorted(missing))}"
    unknown = trigger.keys() - FIELDS
    if unknown:
        return f"unknown fields: {', '.join(sorted(unknown))}"
    if not valid_id(trigger["id_tarea"]):
        return "id_tarea must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}"
    # isinstance first: a list/dict value is unhashable and would crash `in`.
    if not isinstance(trigger["origen"], str) or trigger["origen"] not in ORIGINS:
        return f"origen must be one of {sorted(ORIGINS)}"
    if not isinstance(trigger["prioridad"], str) or trigger["prioridad"] not in PRIORITIES:
        return f"prioridad must be one of {sorted(PRIORITIES)}"
    desc = trigger["descripcion"]
    if not isinstance(desc, str) or not desc.strip() or len(desc) > MAX_DESCRIPTION:
        return f"descripcion must be non-empty text up to {MAX_DESCRIPTION} chars"
    return None


def main():
    try:
        reason = validate(json.load(sys.stdin))
    except Exception as e:  # fail closed
        reason = f"validator error: {e}"
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
