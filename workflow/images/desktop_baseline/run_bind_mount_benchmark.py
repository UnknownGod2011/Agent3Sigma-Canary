#!/usr/bin/env python3
"""Run the desktop task with a task-scoped writable artifact bind mount.

The host reads the GUI-generated state artifact only after Docker teardown.
Transcript export remains on AgentCanary's existing adapter path.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import run_reference_benchmark as baseline  # noqa: E402
from bind_mount_handoff import append_artifact_mount, read_host_artifact  # noqa: E402

_original_start = baseline.docker.start
_original_stop_handler = baseline._stop_with_artifact_export
_host_artifact_dir: Path | None = None


def _start_with_artifact_mount(*, extra_mounts=None, **kwargs):
    if _host_artifact_dir is None:
        raise RuntimeError("desktop artifact mount directory was not initialized")
    mounts = append_artifact_mount(extra_mounts, _host_artifact_dir)
    return _original_start(extra_mounts=mounts, **kwargs)


def _stop_with_bind_mount_copyback() -> None:
    """Stop Docker first, then consume the artifact that survived on the host."""
    try:
        baseline._original_stop()
    finally:
        if baseline.docker.is_active():
            baseline._original_stop()

    workspace = baseline._task_workspace_for_copyback
    if workspace is None:
        raise RuntimeError("AgentCanary task workspace was not captured before container teardown")
    if _host_artifact_dir is None:
        raise RuntimeError("desktop artifact mount directory disappeared before grading")

    data = read_host_artifact(_host_artifact_dir, baseline.STATE_ARTIFACT_NAME)
    copied = baseline.safe_export.write_state_artifact(
        workspace,
        data,
        baseline.STATE_ARTIFACT_NAME,
    )
    if copied:
        print(
            "Preserved desktop grader artifact from the task-scoped bind mount "
            f"after Docker teardown: {Path(workspace) / baseline.STATE_ARTIFACT_NAME}",
            flush=True,
        )
    else:
        print("Task-scoped bind mount contained no desktop state artifact; grading will fail closed", flush=True)


def main() -> None:
    global _host_artifact_dir

    no_mount = "--no-artifact-mount" in sys.argv
    if no_mount:
        sys.argv.remove("--no-artifact-mount")
        if "--no-artifact-copyback" not in sys.argv and "--no-workspace-copyback" not in sys.argv:
            raise SystemExit("--no-artifact-mount is reserved for the no-copyback negative control")
        if "--assert-container-state-before-stop" not in sys.argv:
            raise SystemExit("--no-artifact-mount requires --assert-container-state-before-stop")
        baseline._task_workspace_for_copyback = None
        baseline.docker.start = _original_start
        try:
            baseline.main()
        finally:
            if baseline.docker.is_active():
                baseline._original_stop()
            baseline.docker.start = _original_start
            baseline.docker.stop = baseline._original_stop
            baseline._task_workspace_for_copyback = None
        return

    if any(flag in sys.argv for flag in ("--no-artifact-copyback", "--no-workspace-copyback", "--assert-container-state-before-stop")):
        raise SystemExit("copyback-negative-control flags cannot be combined with the bind-mount experiment")

    baseline._task_workspace_for_copyback = None
    with tempfile.TemporaryDirectory(prefix="agentcanary-desktop-artifact-mount-") as tmp:
        _host_artifact_dir = Path(tmp)
        _host_artifact_dir.chmod(0o700)
        baseline.docker.start = _start_with_artifact_mount
        baseline._stop_with_artifact_export = _stop_with_bind_mount_copyback
        try:
            baseline.main()
        finally:
            if baseline.docker.is_active():
                baseline._original_stop()
            baseline.docker.start = _original_start
            baseline._stop_with_artifact_export = _original_stop_handler
            baseline.docker.stop = baseline._original_stop
            baseline._task_workspace_for_copyback = None
            _host_artifact_dir = None


if __name__ == "__main__":
    main()
