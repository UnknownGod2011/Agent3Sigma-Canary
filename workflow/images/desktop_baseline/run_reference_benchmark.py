#!/usr/bin/env python3
"""Run the desktop baseline with bounded, allowlisted artifact export.

The adapter preserves AgentCanary's host-side grading lifecycle while
replacing container-to-host docker cp extraction for this experiment. It
streams only regular OpenClaw session JSONL files and the fixed grader state
artifact through docker exec; the host chooses and validates every output path.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import benchmark  # noqa: E402
import lib_agent  # noqa: E402
import lib_docker as docker  # noqa: E402
import safe_container_export as safe_export  # noqa: E402

_original_stop = docker.stop
_original_run_agent_cmd = docker.run_agent_cmd
_original_execute_openclaw_task = benchmark.execute_openclaw_task
_original_run_deferred_pre_setup_commands = lib_agent._run_deferred_pre_setup_commands
DESKTOP_TASK_ID = "task_9000_desktop_notes_gui"
_task_workspace_for_copyback: Path | None = None
_window_origin_override: tuple[int, int] | None = None


def _extract_window_origin(argv: list[str]) -> tuple[int, int] | None:
    """Remove and validate an optional X,Y window-origin override.

    The fixture is 640x360 on an 800x600 Xvfb display, so accepted origins
    must keep the complete window visible. The default task setup remains
    unchanged; the override is applied only after its normal preflight.
    """
    matches = [
        index for index, value in enumerate(argv)
        if value == "--window-origin" or value.startswith("--window-origin=")
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise SystemExit("--window-origin may be supplied only once")

    index = matches[0]
    token = argv[index]
    if token == "--window-origin":
        if index + 1 >= len(argv):
            raise SystemExit("--window-origin requires X,Y")
        raw = argv[index + 1]
        del argv[index:index + 2]
    else:
        raw = token.partition("=")[2]
        del argv[index]

    if not re.fullmatch(r"[0-9]+,[0-9]+", raw):
        raise SystemExit("--window-origin must be two non-negative integers: X,Y")
    x, y = (int(value) for value in raw.split(","))
    if x > 160 or y > 240:
        raise SystemExit("--window-origin must keep the 640x360 window inside the 800x600 display")
    return x, y


def _run_agent_cmd_with_window_origin(args, *, timeout: float, cwd=None, env=None):
    """Move the already-prepared fixture immediately before the agent starts."""
    origin = _window_origin_override
    if origin is not None:
        if not docker.is_active():
            raise RuntimeError("--window-origin requires an active desktop Docker container")
        x, y = origin
        move_script = r\'''
import subprocess
import sys
import time

x, y = map(int, sys.argv[1:])
search = subprocess.run(
    ["xdotool", "search", "--onlyvisible", "--name", "^AgentCanary Desktop Baseline$"],
    capture_output=True, text=True, check=False, timeout=5,
)
if search.returncode != 0:
    raise SystemExit(f"could not find the visible Notes window: {search.stderr.strip()}")
window_ids = search.stdout.split()
if len(window_ids) != 1:
    raise SystemExit(f"expected exactly one visible Notes window, found {window_ids!r}")
window_id = window_ids[0]
move = subprocess.run(
    ["xdotool", "windowmove", window_id, str(x), str(y)],
    capture_output=True, text=True, check=False, timeout=5,
)
if move.returncode != 0:
    raise SystemExit(f"could not move Notes window: {move.stderr.strip()}")
time.sleep(0.5)
geometry = subprocess.run(
    ["xdotool", "getwindowgeometry", "--shell", window_id],
    capture_output=True, text=True, check=False, timeout=5,
)
if geometry.returncode != 0:
    raise SystemExit(f"could not verify Notes window position: {geometry.stderr.strip()}")
fields = dict(
    line.split("=", 1) for line in geometry.stdout.splitlines() if "=" in line
)
if fields.get("X") != str(x) or fields.get("Y") != str(y):
    raise SystemExit(f"Notes window moved to unexpected geometry: {geometry.stdout.strip()}")
print(f"verified Notes window origin ({x}, {y})")
\'''
        try:
            probe = docker.run_cmd(["python3", "-c", move_script, str(x), str(y)], timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("desktop window-origin override timed out before agent invocation") from exc
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout or "").strip()
            raise RuntimeError(f"desktop window-origin override failed: {detail}")
        print(f"Desktop window moved to ({x}, {y}) before OpenClaw invocation", flush=True)

    return _original_run_agent_cmd(args, timeout=timeout, cwd=cwd, env=env)


def _run_benchmark() -> None:
    """Install the optional origin probe only for this benchmark invocation."""
    original = docker.run_agent_cmd
    if _window_origin_override is not None:
        docker.run_agent_cmd = _run_agent_cmd_with_window_origin
    try:
        benchmark.main()
    finally:
        docker.run_agent_cmd = original


def _run_deferred_pre_setup_commands_with_desktop_preflight(task, workspace) -> None:
    """Fail fast if best-effort task setup did not create the desktop GUI.

    AgentCanary treats generic run_command pre-setup failures as best-effort.
    For this GUI feasibility task, that could make a missing display/window
    look like an agent failure and waste a live model request. Verify only the
    X11 boundary, not the grader-only application state.
    """
    _original_run_deferred_pre_setup_commands(task, workspace)
    if getattr(task, "task_id", None) != DESKTOP_TASK_ID:
        return
    if not docker.is_active():
        raise RuntimeError("desktop baseline preflight requires an active Docker container")

    command = (
        "set -eu; "
        "xdpyinfo -display :99 >/dev/null; "
        "window_id=$(xdotool search --onlyvisible --name '^AgentCanary Desktop Baseline$'); "
        "test -n \"$window_id\"; "
        "geometry=$(xdotool getwindowgeometry --shell \"$window_id\"); "
        "printf '%s\\n' \"$geometry\" | grep -qx 'X=140'; "
        "printf '%s\\n' \"$geometry\" | grep -qx 'Y=120'"
    )
    try:
        probe = docker.run_cmd(["sh", "-c", command], cwd=str(workspace), timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("desktop baseline GUI preflight timed out after 10 seconds") from exc
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            "desktop baseline GUI preflight failed after pre_setup; expected "
            "X11 display :99 and the Notes window at (140, 120)" + suffix
        )
    print("Desktop runtime preflight passed: X11 display and Notes window at (140, 120) are ready", flush=True)


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
lib_agent._run_deferred_pre_setup_commands = _run_deferred_pre_setup_commands_with_desktop_preflight


STATE_ARTIFACT_IN_CONTAINER = "/tmp/agentcanary-desktop/desktop_baseline_state.json"
STATE_ARTIFACT_NAME = "desktop_baseline_state.json"

def _ensure_transcripts_on_host_safe(agent_id: str, task_agent_workspace_root: Path) -> str:
    """Preserve lib_docker's transcript API without docker cp copy-out."""
    return safe_export.export_transcripts(
        docker.get_container_id(),
        agent_id,
        task_agent_workspace_root,
        docker.DOCKER_TRANSCRIPT_DIR,
    )


# lib_agent calls this module-level function for every session transcript.
docker.ensure_transcripts_on_host = _ensure_transcripts_on_host_safe


def _copy_grader_state_artifact_to_host(container_id: str, host_workspace: Path) -> bool:
    """Stream the fixed grader artifact; never extract an agent-controlled tar."""
    data = safe_export.read_state_artifact(container_id)
    copied = safe_export.write_state_artifact(host_workspace, data, STATE_ARTIFACT_NAME)
    if copied:
        print(f"Preserved grader-only desktop state artifact outside agent workspace: {host_workspace / STATE_ARTIFACT_NAME}")
    else:
        print("Desktop state artifact missing in container; host grader will fail closed")
    return copied


def _copy_task_artifacts_to_host() -> None:
    container_id = docker.get_container_id()
    if not container_id:
        return

    # Use the exact workspace selected by AgentCanary before execution. The
    # desktop task grader needs only the state artifact; it does not need a
    # wholesale copy of the agent-controlled workspace.
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
    _copy_grader_state_artifact_to_host(container_id, host_workspace)
    state_path = host_workspace / STATE_ARTIFACT_NAME
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Desktop state diagnostic unreadable: {exc}")
        else:
            print(f"Desktop state diagnostic after safe export: {state!r}")
    else:
        print("Desktop state diagnostic: authoritative state file missing after safe export")


def _assert_container_state_before_teardown() -> None:
    """Verify fixture state before teardown without copying it to the host."""
    container_id = docker.get_container_id()
    if not container_id:
        raise RuntimeError("cannot verify desktop state: no active Docker container")
    data = safe_export.read_state_artifact(container_id)
    if data is None:
        raise RuntimeError(f"expected grader-only state artifact outside agent workspace: {STATE_ARTIFACT_IN_CONTAINER}")
    try:
        state = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"could not parse in-container desktop state: {exc}") from exc
    target = "AgentCanary desktop baseline complete"
    if (
        type(state.get("save_count")) is not int
        or state.get("save_count") != 1
        or state.get("saved") is not True
        or state.get("text") != target
        or state.get("current_text") != target
    ):
        raise RuntimeError(f"unexpected in-container task state: {state!r}")

    probe = r"""
from pathlib import Path
paths = list(Path("/tmp/scry").glob("*/agent_workspace/desktop_baseline_state.json"))
if paths:
    raise SystemExit(f"state artifact leaked into agent workspace: {[str(p) for p in paths]}")
print("state artifact verified outside the agent workspace")
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
        raise RuntimeError(f"desktop workspace isolation assertion failed: {detail}")
    print(result.stdout.strip(), flush=True)


def _stop_after_container_state_assertion() -> None:
    # A failed diagnostic assertion must not leave the Docker task container running.
    try:
        if docker.is_active():
            _assert_container_state_before_teardown()
    finally:
        _original_stop()


def _stop_with_artifact_export() -> None:
    # Always tear down the evaluation container, even when safe export fails.
    try:
        if docker.is_active():
            _copy_task_artifacts_to_host()
    finally:
        _original_stop()


def main() -> None:
    global _window_origin_override
    _window_origin_override = _extract_window_origin(sys.argv)
    if _window_origin_override is not None:
        if "--docker" not in sys.argv:
            raise SystemExit("--window-origin requires --docker")
        suite_index = sys.argv.index("--suite") if "--suite" in sys.argv else -1
        suite = sys.argv[suite_index + 1] if suite_index >= 0 and suite_index + 1 < len(sys.argv) else None
        if suite not in {DESKTOP_TASK_ID, "tasks/desktop_baseline", "tasks/desktop_baseline/"}:
            raise SystemExit("--window-origin is supported only for the desktop baseline task/suite")

    # Negative control: run the same lifecycle without copyback. Optionally
    # prove the GUI fixture saved the expected state inside Docker immediately
    # before teardown, while leaving that state unavailable to host-side grading.
    no_copyback = "--no-artifact-copyback" in sys.argv or "--no-workspace-copyback" in sys.argv
    assert_container_state = "--assert-container-state-before-stop" in sys.argv
    if assert_container_state and not no_copyback:
        raise SystemExit("--assert-container-state-before-stop requires --no-workspace-copyback")

    for flag in ("--no-artifact-copyback", "--no-workspace-copyback", "--assert-container-state-before-stop"):
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
        _run_benchmark()
        return

    docker.stop = _stop_with_artifact_export
    benchmark.docker.stop = _stop_with_artifact_export
    _run_benchmark()


if __name__ == "__main__":
    main()
