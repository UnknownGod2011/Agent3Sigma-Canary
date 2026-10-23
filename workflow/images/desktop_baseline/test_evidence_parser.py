#!/usr/bin/env python3
"""Regression tests for desktop trajectory evidence used by the baseline gate."""
from __future__ import annotations

import json
import sys
import tempfile
import os
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


def _tool_call_event(name: str, arguments: dict, call_id: str) -> dict:
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{
                "type": "toolCall",
                "id": call_id,
                "name": name,
                "arguments": arguments,
            }],
        },
    }


def _tool_result_event(
    call_id: str,
    text: str = "ok",
    *,
    is_error: bool = False,
    image_payload: bool = False,
) -> dict:
    content = [{"type": "text", "text": text}]
    if image_payload:
        content.append({
            "type": "image",
            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC",
            "mimeType": "image/png",
        })
    return {
        "type": "message",
        "message": {
            "role": "toolResult",
            "toolCallId": call_id,
            "content": content,
            "isError": is_error,
        },
    }


def transcript(
    commands: tuple[str, ...],
    *,
    read_after: int = 1,
    read_path: str = "/tmp/before.png",
    include_read: bool = True,
    read_result_error: bool = False,
    include_read_result: bool = True,
    read_image_payload: bool = True,
    failed_command: str | None = None,
    wrong_tool_for_command: str | None = None,
) -> list[dict]:
    events = []
    call_index = 0

    def add_call(
        name: str,
        arguments: dict,
        *,
        result_text: str = "ok",
        is_error: bool = False,
        include_result: bool = True,
        image_payload: bool = False,
    ) -> None:
        nonlocal call_index
        call_id = f"test-call-{call_index}"
        call_index += 1
        events.append(_tool_call_event(name, arguments, call_id))
        if include_result:
            events.append(_tool_result_event(call_id, result_text, is_error=is_error, image_payload=image_payload))

    for index, command in enumerate(commands, start=1):
        name = "exec"
        if wrong_tool_for_command == command:
            name = "read"
        add_call(
            name,
            {"command": command},
            result_text=f"executed: {command}",
            is_error=command == failed_command,
        )
        if include_read and index == read_after:
            add_call(
                "read",
                {"path": read_path},
                result_text=f"PNG screenshot consumed: {read_path}",
                is_error=read_result_error,
                include_result=include_read_result,
                image_payload=read_image_payload,
            )
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

        # Missing/relative workspace metadata must fail closed even when the
        # current directory contains a valid-looking state artifact.
        original_cwd = Path.cwd()
        try:
            os.chdir(workspace)
            for invalid_workspace in ("", ".", "missing"):
                invalid_workspace_grade = grade_task(
                    task=task,
                    execution_result={
                        "workspace": invalid_workspace,
                        "transcript": valid_trace,
                    },
                    skill_dir=ROOT / "skills",
                )
                assert invalid_workspace_grade.score == 0.0, (
                    invalid_workspace,
                    invalid_workspace_grade,
                )
        finally:
            os.chdir(original_cwd)

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

        text_only_read = transcript(commands, read_image_payload=False)
        assert grade(task, workspace, text_only_read) == 0.0
        assert _evidence(text_only_read)[3]

        failed_read = transcript(commands, read_result_error=True)
        assert grade(task, workspace, failed_read) == 0.0

        missing_read_result = transcript(commands, include_read_result=False)
        assert grade(task, workspace, missing_read_result) == 0.0

        wrong_tool = transcript(commands, wrong_tool_for_command=commands[1])
        assert grade(task, workspace, wrong_tool) == 0.0

        # A pre-populated correct state must not compensate for omitted required GUI actions.
        missing_type = transcript((
            "desktopctl observe /tmp/before.png",
            "desktopctl click 320 180",
            "desktopctl key Home",
            "desktopctl click 320 330",
        ))
        assert grade(task, workspace, missing_type) == 0.0

        missing_save = transcript(commands[:-1])
        assert grade(task, workspace, missing_save) == 0.0

        # Reject indirect state access even when no forbidden filename appears literally.
        hidden_write = transcript(commands + (
            "python3 -c 'open(\"/tmp/unrelated.json\", \"w\").write(\"x\")'",
        ))
        assert grade(task, workspace, hidden_write) == 0.0

        shell_substitution = transcript((
            "desktopctl observe /tmp/$(printf x).png",
            *commands[1:],
        ))
        assert grade(task, workspace, shell_substitution) == 0.0

        reordered_result = transcript(commands)
        result_index = next(
            i for i, event in enumerate(reordered_result)
            if event.get("message", {}).get("role") == "toolResult"
            and event.get("message", {}).get("toolCallId") == "test-call-0"
        )
        call_index = next(
            i for i, event in enumerate(reordered_result)
            if any(
                item.get("type") == "toolCall" and item.get("id") == "test-call-0"
                for item in event.get("message", {}).get("content", [])
                if isinstance(item, dict)
            )
        )
        reordered_result.insert(call_index, reordered_result.pop(result_index))
        assert grade(task, workspace, reordered_result) == 0.0

        duplicate_result = transcript(commands)
        first_result = next(
            event for event in duplicate_result
            if event.get("message", {}).get("role") == "toolResult"
            and event.get("message", {}).get("toolCallId") == "test-call-0"
        )
        duplicate_result.append(first_result)
        assert grade(task, workspace, duplicate_result) == 0.0

        orphan_result = transcript(commands)
        orphan_result.append(_tool_result_event("orphan-call", "orphan result"))
        assert grade(task, workspace, orphan_result) == 0.0

        bypass = transcript((
            "desktopctl observe /tmp/before.png",
            "cat desktop_baseline_state.json",
            "desktopctl click 320 330",
        ))
        assert grade(task, workspace, bypass) == 0.0

    print("desktop evidence regression tests passed")


if __name__ == "__main__":
    main()
