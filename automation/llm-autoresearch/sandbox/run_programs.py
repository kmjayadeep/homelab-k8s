"""Execute each JSONL program from stdin in its own interpreter; print pass/fail JSONL."""

import json
import subprocess
import sys
import tempfile

TIMEOUT = 60

for line in sys.stdin:
    row = json.loads(line)
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir="/tmp", delete=False) as f:
        f.write(row["program"])
        path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, "-I", path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd="/tmp",
        )
        passed = proc.returncode == 0
        lines = proc.stderr.strip().splitlines()
        error = None if passed else (lines[-1][:200] if lines else f"exit {proc.returncode}")
    except subprocess.TimeoutExpired:
        passed, error = False, f"timeout after {TIMEOUT}s"
    print(json.dumps({"key": row["key"], "pass": passed, "error": error}), flush=True)
