#!/usr/bin/env python3
"""Docker-backed regression for required run_command setup failure."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow.images.desktop_baseline import run_reference_benchmark as runner  # noqa: E402

TASK_ID = "task_9001_required_setup_failure"
TASK_FILE = ROOT / "tasks" / "desktop_baseline" / f"{TASK_ID}.md"
TASK_SOURCE = """---
id: task_9001_required_setup_failure
name: "Required setup failure must abort before agent invocation"
category: desktop_baseline
grading_type: automated
timeout_seconds: 30
required_skills: []
pre_setup:
  - type: run_command
    required: true
    command: "exit 17"
---

## Prompt

This prompt must not be sent to an agent because required setup fails first.

## Expected Behavior

The required setup command exits with status 17. AgentCanary must record an execution error, preserve an empty transcript, stop the Docker container, and grade this invalid run as zero.

## Grading Criteria

- The task must not be executed after required setup fails.

## Automated Checks

\x60\x60\x60python
def grade(transcript: list, workspace_path: str) -> dict:
    return {"required_setup_failure": 0.0}
\x60\x60\x60
"""


def main() -> None:
    if not os.environ.get("DOCKER_IMAGE"):
        raise SystemExit("DOCKER_IMAGE must name the already-built desktop baseline image")
    if TASK_FILE.exists():
        raise SystemExit(f"refusing to overwrite existing task file: {TASK_FILE}")

    original_argv = sys.argv[:]
    original_run_cmd = runner.docker.run_cmd
    original_stop = runner._original_stop
    recorded_commands: list[tuple[str, ...]] = []
    workspace: Path | None = None
    TASK_FILE.write_text(TASK_SOURCE, encoding="utf-8")

    try:
        def recording_run_cmd(args, **kwargs):
            recorded_commands.append(tuple(str(arg) for arg in args))
            return original_run_cmd(args, **kwargs)

        runner.docker.run_cmd = recording_run_cmd
        with tempfile.TemporaryDirectory(prefix="agentcanary-required-setup-") as tmp:
            output_dir = Path(tmp) / "results"
            sys.argv = [
                "run_reference_benchmark.py",
                "--model", "reference/desktop",
                "--suite", TASK_ID,
                "--docker",
                "--timeout-multiplier", "1.0",
                "--output-dir", str(output_dir),
                "--verbose",
            ]
            runner.main()

            if runner.docker.is_active() or runner.docker.get_container_id() is not None:
                raise AssertionError("Docker container remained active after required setup failure")
            if not any(command == ("sh", "-c", "exit 17") for command in recorded_commands):
                raise AssertionError(f"required setup command was not executed: {recorded_commands!r}")
            if any(
                len(command) >= 2 and command[:2] == ("openclaw", "agent")
                for command in recorded_commands
            ):
                raise AssertionError(
                    f"OpenClaw agent invocation occurred after required setup failure: {recorded_commands!r}"
                )

            result_files = list(output_dir.glob(f"job_*/task_{TASK_ID}/task_{TASK_ID}.json"))
            if len(result_files) != 1:
                raise AssertionError(f"expected exactly one task result, found {result_files!r}")
            result = json.loads(result_files[0].read_text(encoding="utf-8"))
            grading = result.get("grading", {})
            if result.get("task_id") != TASK_ID or result.get("status") != "error":
                raise AssertionError(f"unexpected execution result: {result!r}")
            if (
                result.get("transcript") != []
                or result.get("transcript_length") != 0
                or result.get("transcript_path") is not None
            ):
                raise AssertionError(f"failed setup produced transcript evidence: {result!r}")
            if grading.get("score") != 0.0 or grading.get("max_score") != 1.0:
                raise AssertionError(f"failed setup was not graded zero: {grading!r}")
            if grading.get("breakdown", {}).get("required_setup_failure") != 0.0:
                raise AssertionError(f"unexpected grading breakdown: {grading!r}")
            if "required pre_setup command failed: exited with status 17" not in str(result.get("stderr", "")):
                raise AssertionError(
                    f"required setup failure was not recorded: {result.get('stderr')!r}"
                )

            workspace = runner._task_workspace_for_copyback
            if workspace is None:
                raise AssertionError("desktop adapter did not capture the task workspace")
            state_artifact = workspace / "desktop_baseline_state.json"
            if state_artifact.exists():
                raise AssertionError(
                    f"unexpected grader state artifact leaked to host workspace: {state_artifact}"
                )

        print(
            "Docker-backed required setup failure regression passed: no agent invocation, "
            "empty transcript, zero grade, container stopped, no state artifact copied back"
        )
    finally:
        workspace = workspace or runner._task_workspace_for_copyback
        if runner.docker.is_active():
            try:
                runner._original_stop()
            except Exception:
                pass
        runner.docker.run_cmd = original_run_cmd
        runner.docker.stop = original_stop
        runner.benchmark.docker.stop = original_stop
        runner._task_workspace_for_copyback = None
        sys.argv = original_argv
        TASK_FILE.unlink(missing_ok=True)
        if workspace is not None:
            shutil.rmtree(workspace.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
