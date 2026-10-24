#!/usr/bin/env python3
"""Regression test that manual desktop runs cannot verify stale result artifacts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "task_9000_desktop_notes_gui"
VERIFIER = ROOT / "workflow" / "images" / "desktop_baseline" / "verify_benchmark.py"
SCRIPT = ROOT / "workflow" / "images" / "desktop_baseline" / "run_benchmark.sh"
SOURCE = SCRIPT.read_text(encoding="utf-8")
START_MARKER = "# Treat this variable as a results root, not a reusable output directory."
END_MARKER = "\n\n# Preserve the task workspace before AgentCanary removes its Docker container."
start = SOURCE.index(START_MARKER)
end = SOURCE.index(END_MARKER, start)
ALLOCATION_SNIPPET = SOURCE[start:end]


def allocate_results_dir(root: Path) -> Path:
    env = os.environ.copy()
    env["AGENTCANARY_DESKTOP_RESULTS"] = str(root)
    command = ALLOCATION_SNIPPET + '\nprintf "__RESULTS_DIR__%s\\n" "$RESULTS_DIR"\n'
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    paths = [
        line.removeprefix("__RESULTS_DIR__")
        for line in result.stdout.splitlines()
        if line.startswith("__RESULTS_DIR__")
    ]
    assert len(paths) == 1, result.stdout
    return Path(paths[0])


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "results"
        stale = root / "job_1" / TASK_ID / f"{TASK_ID}.json"
        stale.parent.mkdir(parents=True)
        stale_payload = {"task_id": "task_9000_desktop_notes_gui", "grading": {"score": 1.0, "max_score": 1.0}}
        stale.write_text(json.dumps(stale_payload) + chr(10), encoding="utf-8")
        assert json.loads(stale.read_text(encoding="utf-8")) == stale_payload

        # Prove the fixture matches the verifier's real artifact glob. The
        # verifier must discover it under a reused shared root (then reject its
        # incomplete evidence), so this test cannot pass with a misshapen fixture.
        shared_root_check = subprocess.run(
            [sys.executable, str(VERIFIER), str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert shared_root_check.returncode == 1, (
            shared_root_check.returncode,
            shared_root_check.stdout,
            shared_root_check.stderr,
        )
        assert f"no {TASK_ID} benchmark artifact found under {root}" not in shared_root_check.stderr, (
            "stale fixture did not match the verifier's artifact glob",
            shared_root_check.stderr,
        )
        assert "desktop benchmark verification failed:" in shared_root_check.stderr, (
            "expected the deliberately incomplete stale fixture to fail closed",
            shared_root_check.stderr,
        )

        first = allocate_results_dir(root)
        second = allocate_results_dir(root)

        assert first != second, (first, second)
        assert first.parent == root and second.parent == root, (first, second)
        assert first.is_dir() and second.is_dir()
        assert not any(first.iterdir()), list(first.iterdir())
        assert not any(second.iterdir()), list(second.iterdir())

        # The actual verifier, given a fresh attempt directory, must not walk
        # up to the shared root and select the stale artifact beside it.
        isolated_check = subprocess.run(
            [sys.executable, str(VERIFIER), str(first)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert isolated_check.returncode == 1, (
            isolated_check.returncode,
            isolated_check.stdout,
            isolated_check.stderr,
        )
        assert f"error: no {TASK_ID} benchmark artifact found under {first}" in isolated_check.stderr, (
            "fresh attempt unexpectedly discovered an artifact outside its directory",
            isolated_check.stderr,
        )

        assert stale.is_file(), "older results must be preserved, not deleted"
        assert '--output-dir "$RESULTS_DIR"' in SOURCE
        assert 'verify_benchmark.py "$RESULTS_DIR"' in SOURCE

    print("desktop result-directory isolation and verifier-scope tests passed")


if __name__ == "__main__":
    main()
