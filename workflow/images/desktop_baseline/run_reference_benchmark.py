#!/usr/bin/env python3
"""Run the desktop reference lifecycle while preserving Docker task outputs.

This is an experimental desktop/UI baseline adapter. AgentCanary's Docker
lifecycle removes the container before host-side automated grading, so this
wrapper preserves the task workspace and separately exports the deterministic
state artifact from `/tmp/agentcanary-desktop/` into the host grading workspace.

The state artifact stays outside the agent workspace during the evaluated
interaction. The wrapper copies it only after the agent run, immediately before
container teardown, so the existing host-side grader can independently verify
the GUI result without exposing the artifact as a workspace file to the agent.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import benchmark  # noqa: E402
import lib_docker as docker  # noqa: E402

_original_stop = docker.stop
_original_execute_openclaw_task = benchmark.execute_openclaw_task
_task_workspace_for_copyback: Path | None = None


def _capture_task_workspace(*args, **kwargs):
    """Capture the exact AgentCanary workspace before its Docker lifecycle runs."""
    global _task_workspace_for_copyback
    workspace = kwargs.get("task_agent_workspace_root_relate")
    if not isinstance(workspace, (str, Path)):
        raise RuntimeError(
            "AgentCanary did not provide a task workspace to the desktop adapter"
        )

    workspace_path = Path(workspace)
    if (
        _task_workspace_for_copyback is not None
        and _task_workspace_for_copyback != workspace_path
    ):
        raise RuntimeError("desktop baseline adapter expected a single task workspace")

    _task_workspace_for_copyback = workspace_path
    return _original_execute_openclaw_task(*args, **kwargs)


# Capture the runner-selected path before task execution; do not discover a
# potentially agent-created lookalike directory after the run.
benchmark.execute_openclaw_task = _capture_task_workspace


STATE_ARTIFACT_IN_CONTAINER = "/tmp/agentcanary-desktop/desktop_baseline_state.json"
STATE_ARTIFACT_NAME = "desktop_baseline_state.json"


def _remove_path(path: Path) -> None:
    """Remove an agent-controlled path without following a symlink."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _copy_grader_state_artifact_to_host(container_id: str, host_workspace: Path) -> bool:
    """Copy the authoritative GUI state only after the evaluated interaction.

    Any same-named file copied from the agent workspace is discarded first.
    Missing state is a normal task failure and must grade fail-closed; Docker
    transport errors are harness failures and remain visible to the caller.
    """
    host_state_path = host_workspace / STATE_ARTIFACT_NAME
    temporary_copy = host_workspace / ".desktop_baseline_state.json.copyback"
    _remove_path(host_state_path)
    _remove_path(temporary_copy)

    probe_command = (
        f"if [ -f {STATE_ARTIFACT_IN_CONTAINER} ]; "
        "then printf present; else printf missing; fi"
    )
    probe = subprocess.run(
        ["docker", "exec", container_id, "sh", "-c", probe_command],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise RuntimeError(f"failed to probe desktop state artifact: {detail}")

    status = probe.stdout.strip()
    if status == "missing":
        print("Desktop state artifact missing in container; host grader will fail closed")
        return False
    if status != "present":
        raise RuntimeError(f"unexpected desktop state probe output: {status!r}")

    copy_result = subprocess.run(
        [
            "docker",
            "cp",
            f"{container_id}:{STATE_ARTIFACT_IN_CONTAINER}",
            str(temporary_copy),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if copy_result.returncode != 0:
        _remove_path(temporary_copy)
        detail = (copy_result.stderr or copy_result.stdout).strip()
        raise RuntimeError(f"failed to preserve grader-only desktop state artifact: {detail}")

    temporary_copy.replace(host_state_path)
    print(f"Preserved grader-only desktop state artifact outside agent workspace: {host_state_path}")
    return True


def _copy_task_workspaces_to_host() -> None:
    container_id = docker.get_container_id()
    if not container_id:
        return

    # This adapter runs one desktop task. Use the exact workspace path selected
    # by AgentCanary, captured before execution, instead of searching a tree the
    # evaluated process can mutate.
    container_workspace = _task_workspace_for_copyback
    if container_workspace is None:
        raise RuntimeError("AgentCanary task workspace was not captured before grading")

    parts = container_workspace.parts
    if (
        len(parts) != 5
        or parts[1] != "tmp"
        or parts[2] != "scry"
        or not re.fullmatch(r"[0-9a-f]{32}", parts[3])
        or parts[4] != "agent_workspace"
    ):
        raise RuntimeError(f"refusing unexpected workspace path: {container_workspace}")

    host_workspace = container_workspace
    host_workspace.mkdir(parents=True, exist_ok=True)
    copy_result = subprocess.run(
        [
            "docker",
            "cp",
            f"{container_id}:{container_workspace}/.",
            str(host_workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if copy_result.returncode != 0:
        raise RuntimeError(
            "failed to preserve Docker task workspace: "
            + (copy_result.stderr or copy_result.stdout).strip()
        )
    print(f"Preserved Docker task workspace for host grading: {host_workspace}")

    # Replace any same-named workspace artifact with the authoritative state
    # kept outside the workspace during agent execution.
    _copy_grader_state_artifact_to_host(container_id, host_workspace)
    state_path = host_workspace / STATE_ARTIFACT_NAME
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Desktop state diagnostic unreadable: {exc}")
        else:
            print(f"Desktop state diagnostic after authoritative copyback: {state!r}")
    else:
        print("Desktop state diagnostic: authoritative state file missing after copyback")

def _assert_container_state_before_teardown() -> None:
    """Verify the fixture saved correctly inside Docker before the container is removed.

    This is a harness-side negative-control assertion. It deliberately does not
    copy the state file to the host, so the normal host grader still cannot see it.
    """
    container_id = docker.get_container_id()
    if not container_id:
        raise RuntimeError("cannot verify desktop state: no active Docker container")

    probe = r"""
import json
from pathlib import Path

target = "AgentCanary desktop baseline complete"
path = Path("/tmp/agentcanary-desktop/desktop_baseline_state.json")
if not path.is_file():
    raise SystemExit(f"expected grader-only state artifact outside agent workspace: {path}")
workspace_state_paths = list(Path("/tmp/scry").glob("*/agent_workspace/desktop_baseline_state.json"))
if workspace_state_paths:
    raise SystemExit(f"state artifact leaked into agent workspace: {[str(p) for p in workspace_state_paths]}")
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"could not read in-container task state: {exc}")
if state.get("saved") is not True or state.get("text") != target or state.get("current_text") != target:
    raise SystemExit(f"unexpected in-container task state at {path}: {state!r}")
print(f"pre-teardown state verified inside container: saved={state['saved']}, text={state['text']!r}, current_text={state['current_text']!r}")
"""
    result = subprocess.run(
        ["docker", "exec", container_id, "python3", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"pre-teardown desktop state verification failed: {detail}")
    print(result.stdout.strip(), flush=True)


def _stop_after_container_state_assertion() -> None:
    if docker.is_active():
        _assert_container_state_before_teardown()
    _original_stop()


def _stop_with_workspace_copyback() -> None:
    # Always tear down the evaluation container, even when preserving the
    # workspace fails. Keep the copyback exception visible to the caller.
    try:
        if docker.is_active():
            _copy_task_workspaces_to_host()
    finally:
        _original_stop()


def main() -> None:
    # Negative control: run the same lifecycle without copyback. Optionally
    # prove the GUI fixture saved the expected state inside Docker immediately
    # before teardown, while leaving that state unavailable to host-side grading.
    no_copyback = "--no-workspace-copyback" in sys.argv
    assert_container_state = "--assert-container-state-before-stop" in sys.argv
    if assert_container_state and not no_copyback:
        raise SystemExit("--assert-container-state-before-stop requires --no-workspace-copyback")

    for flag in ("--no-workspace-copyback", "--assert-container-state-before-stop"):
        if flag in sys.argv:
            sys.argv.remove(flag)

    if no_copyback:
        if assert_container_state:
            docker.stop = _stop_after_container_state_assertion
            benchmark.docker.stop = _stop_after_container_state_assertion
            print(
                "Running negative control without workspace copyback; "
                "checking saved state inside Docker before teardown",
                flush=True,
            )
        else:
            print("Running negative control without workspace copyback", flush=True)
        benchmark.main()
        return

    docker.stop = _stop_with_workspace_copyback
    benchmark.docker.stop = _stop_with_workspace_copyback
    benchmark.main()


if __name__ == "__main__":
    main()
