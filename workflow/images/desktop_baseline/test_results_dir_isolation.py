#!/usr/bin/env python3
"""Regression test that manual desktop runs cannot verify stale result artifacts."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
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
        stale = root / "old-run" / "job_1" / "task_9000" / "task_9000.json"
        stale.parent.mkdir(parents=True)
        stale.write_text('{"grading":{"score":1.0}}\\n', encoding="utf-8")

        first = allocate_results_dir(root)
        second = allocate_results_dir(root)

        assert first != second, (first, second)
        assert first.parent == root and second.parent == root, (first, second)
        assert first.is_dir() and second.is_dir()
        assert not any(first.iterdir()), list(first.iterdir())
        assert not any(second.iterdir()), list(second.iterdir())
        assert stale.is_file(), "older results must be preserved, not deleted"
        assert '--output-dir "$RESULTS_DIR"' in SOURCE
        assert 'verify_benchmark.py "$RESULTS_DIR"' in SOURCE

    print("desktop result-directory isolation tests passed (unique, empty, stale-safe)")


if __name__ == "__main__":
    main()
