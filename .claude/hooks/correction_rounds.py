"""Stage E correction-round counter (ADR-002).

Each call requests one more correction round for a task.
stdin:  {"id_tarea": "...", "state_dir": "<dir for counters>"}
stdout: "round N" when allowed
exit:   0 = round granted, 2 = cap reached or error -> escalate to human.

A corrupt or tampered counter counts as cap reached (fail closed).
"""
import json
import os
import sys
from pathlib import Path

from validate_trigger import valid_id

MAX_ROUNDS = 2


def request_round(id_tarea, state_dir):
    if not valid_id(id_tarea):
        raise ValueError("invalid id_tarea")
    if not isinstance(state_dir, str) or not state_dir:
        raise ValueError("state_dir is required")
    counter = Path(state_dir) / f"{id_tarea}.json"
    used = 0
    if counter.exists():
        used = json.loads(counter.read_text())["rounds"]
        if type(used) is not int or used < 0:
            raise ValueError(f"tampered counter: {counter}")
    if used >= MAX_ROUNDS:
        return None
    # ponytail: no file lock; one Validator per task. Add fcntl.flock if tasks run concurrently.
    tmp = counter.with_suffix(".tmp")
    tmp.write_text(json.dumps({"rounds": used + 1}))
    os.replace(tmp, counter)
    return used + 1


def main():
    try:
        payload = json.load(sys.stdin)
        granted = request_round(payload["id_tarea"], payload.get("state_dir"))
        reason = None if granted else f"cap of {MAX_ROUNDS} rounds reached"
    except Exception as e:  # fail closed
        granted, reason = None, f"counter error: {e}"
    if granted:
        print(f"round {granted}")
        return 0
    print(f"{reason}; escalate to human", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
