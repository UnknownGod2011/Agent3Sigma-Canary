#!/usr/bin/env python3
"""Regression tests for keeping the experimental desktop suite opt-in."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import benchmark  # noqa: E402


def make_task(task_id: str, relative_path: str, grading_type: str = "automated"):
    return SimpleNamespace(
        task_id=task_id,
        grading_type=grading_type,
        file_path=ROOT / "tasks" / relative_path,
    )


def main() -> None:
    desktop = make_task(
        "task_9000_desktop_notes_gui",
        "desktop_baseline/task_9000_desktop_notes_gui.md",
    )
    root_task = make_task("task_00_sanity", "task_00_sanity.md")
    direct_task = make_task("task_30_example", "direct/task_30_example.md")
    tasks = [desktop, root_task, direct_task]

    assert benchmark._select_task_ids(tasks, "desktop_baseline") == [desktop.task_id]
    assert benchmark._select_task_ids(tasks, "non-security") == [root_task.task_id]
    assert benchmark._select_task_ids(tasks, "task_9000") == ["task_9000"]

    # Broad suites must not silently run this task: it requires the dedicated
    # desktop image plus the wrapper that exports its grader artifact before
    # the normal host-side grading step.
    expected_standard = [root_task.task_id, direct_task.task_id]
    assert benchmark._select_task_ids(tasks, "all") == expected_standard
    assert benchmark._select_task_ids(tasks, "automated-only") == expected_standard

    print("desktop suite selection tests passed (5 selector assertions)")


if __name__ == "__main__":
    main()
