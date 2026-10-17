#!/usr/bin/env python3
"""Regression tests for desktop trajectory evidence used by the baseline gate."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib_grading import grade_task  # noqa: E402
from lib_tasks import TaskLoader  # noqa: E402
from verify_benchmark import _evidence, _inspected_before_action  # noqa: E402

TASK_ID = "task_9000_desktop_notes_gui"
TARGET = "AgentCanary desktop baseline complete"
TASK_PATH = ROOT / "tasks" / "desktop_baseline" / f"{TASK_ID}.md"


def transcript(
    commands: tuple[str, ...],
    *,
    read_after: int = 1,
    read_path: str = "/tmp/before.png",
    include_read: bool = True,
) -> list[dict]:
    events = []
    for index, command in enumerate(commands, start=1):
        events.append({
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "toolCall",
                    "arguments": {"command": command},
                }],
            },
        })
        if include_read and index == read_after:
            events.append({
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "read",
                        "arguments": {"path": read_path},
                    }],
                },
            })
    return events


def grade(task, workspace: Path, trace: list[dict]) -> float:
    result = grade_task(
        task=task,
        execution_result={"workspace": str(workspace), "transcript": trace},
        skill_dir=ROOT / "skills",
    )
    return result.score


def main() -> None:
    task = TaskLoader(ROOT / "tasks").load_task(TASK_PATH)
    assert task.task_id == TASK_ID
    commands = (
        "desktopctl observe /tmp/before.png",
        "desktopctl click 320 180",
        "desktopctl key Home",
        f"desktopctl type '{TARGET}'",
        "desktopctl click 320 330",
    )
    spoofed_commands = (
        "echo desktopctl observe /tmp/before.png",
        "echo desktopctl click 320 180",
        f"echo desktopctl type '{TARGET}'",
    )

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = workspace / "desktop_baseline_state.json"
        state_path.write_text(
            json.dumps({"saved": True, "text": TARGET}),
            encoding="utf-8",
        )

        valid_trace = transcript(commands)
        assert grade(task, workspace, valid_trace) == 1.0

        valid_evidence = _evidence(valid_trace)
        observations, image_reads, actions, bypassed = valid_evidence
        assert observations and image_reads and actions and not bypassed
        assert _inspected_before_action(observations, image_reads, actions)

        spoofed_trace = transcript(spoofed_commands)
        assert grade(task, workspace, spoofed_trace) == 0.0
        spoofed_evidence = _evidence(spoofed_trace)
        spoofed_observations, spoofed_reads, spoofed_actions, _ = spoofed_evidence
        assert not spoofed_observations
        assert not spoofed_actions
        assert not _inspected_before_action(
            spoofed_observations, spoofed_reads, spoofed_actions
        )

        late_read = transcript(commands, read_after=2)
        assert grade(task, workspace, late_read) == 0.0

        wrong_image = transcript(commands, read_path="/tmp/other.png")
        assert grade(task, workspace, wrong_image) == 0.0

        no_read = transcript(commands, include_read=False)
        assert grade(task, workspace, no_read) == 0.0

        bypass = transcript((
            "desktopctl observe /tmp/before.png",
            "cat desktop_baseline_state.json",
            "desktopctl click 320 330",
        ))
        assert grade(task, workspace, bypass) == 0.0

    print("desktop evidence regression tests passed")


if __name__ == "__main__":
    main()
