#!/usr/bin/env python3
"""Characterize desktop-task integration against the current upstream runner.

This is intentionally a characterization test, not a production-code patch.
It records which parts of the desktop path are already supported by upstream
and which still require the fork's desktop-specific wrapper.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import benchmark  # noqa: E402
import lib_agent  # noqa: E402
from lib_task_validation import validate_task_toolsets  # noqa: E402
from lib_tasks import TaskLoader  # noqa: E402

TASK_PATH = ROOT / "tasks" / "desktop_baseline" / "task_9000_desktop_notes_gui.md"
TASK_ID = "task_9000_desktop_notes_gui"


def load_desktop_task():
    assert TASK_PATH.is_file(), f"desktop task overlay missing: {TASK_PATH}"
    task = TaskLoader(ROOT / "tasks").load_task(TASK_PATH)
    assert task.task_id == TASK_ID, task.task_id
    return task


def characterize_suite_selection(task) -> None:
    ordinary = SimpleNamespace(
        task_id="task_00_sanity",
        grading_type="automated",
        file_path=ROOT / "tasks" / "task_00_sanity.md",
    )
    tasks = [ordinary, task]

    # Upstream's path-based selector can run the experimental directory
    # explicitly. Both documented path spellings normalize to that directory.
    assert benchmark._select_tasks(tasks, "desktop_baseline/") == [task]
    assert benchmark._select_tasks(tasks, "tasks/desktop_baseline/") == [task]

    # But the default broad suites currently include the desktop task. This is
    # important because the task needs a GUI-capable image and a post-run
    # artifact handoff that ordinary images/runs do not provide.
    assert task in benchmark._select_tasks(tasks, "all")
    assert task in benchmark._select_tasks(tasks, "automated-only")
    assert task in benchmark._select_tasks(tasks, "non-security")


def characterize_toolset_validation(task) -> None:
    # The current task has no declared toolset, so upstream accepts it even
    # when the selected image is an ordinary non-desktop OpenClaw image.
    assert not task.frontmatter.get("required_toolset")
    validate_task_toolsets([task], "openclaw-official", docker_mode=True)

    # A natural explicit declaration is not yet supported: the current
    # validator recognizes only safety_research and rejects "desktop".
    desktop_requirement = SimpleNamespace(
        task_id=task.task_id,
        frontmatter={**task.frontmatter, "required_toolset": "desktop"},
    )
    try:
        validate_task_toolsets(
            [desktop_requirement], "openclaw-official", docker_mode=True
        )
    except ValueError as exc:
        assert "unknown required_toolset 'desktop'" in str(exc), str(exc)
    else:
        raise AssertionError("upstream unexpectedly accepted required_toolset: desktop")


def characterize_pre_setup_failure_semantics(task) -> None:
    # run_command is deliberately best-effort in upstream. A failed Xvfb/Tk
    # launch is logged and skipped rather than aborting before the model call.
    failed = subprocess.CompletedProcess(
        args=["sh", "-c", "false"],
        returncode=1,
        stdout="",
        stderr="simulated missing X11 runtime",
    )
    with (
        patch.object(lib_agent.docker, "is_active", return_value=True),
        patch.object(lib_agent.docker, "run_cmd", return_value=failed) as run_cmd,
    ):
        lib_agent._execute_run_command_setup(
            {"command": "false"}, ROOT / "tmp-workspace", task.task_id
        )
    run_cmd.assert_called_once()


def main() -> None:
    task = load_desktop_task()
    characterize_suite_selection(task)
    characterize_toolset_validation(task)
    characterize_pre_setup_failure_semantics(task)
    print(
        "upstream desktop characterization passed: explicit directory selection "
        "works; broad suites include the desktop task; desktop toolset validation "
        "is unsupported; run_command setup failures remain best-effort"
    )


if __name__ == "__main__":
    main()
