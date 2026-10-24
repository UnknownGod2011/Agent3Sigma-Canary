#!/usr/bin/env python3
"""Regression tests for desktop trajectory evidence used by the baseline gate."""
from __future__ import annotations

import base64
import json
import os
import struct
import sys
import tempfile
import zlib
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
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600


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
            "data": valid_screenshot_payload(),
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


def replace_image_payload(trace: list[dict], payload: str, mime_type: str | None = None) -> None:
    found = False
    for event in trace:
        message = event.get("message", {})
        if message.get("role") != "toolResult":
            continue
        for block in message.get("content", []):
            if isinstance(block, dict) and block.get("type") == "image":
                block["data"] = payload
                if mime_type is not None:
                    block["mimeType"] = mime_type
                found = True
    assert found, "test trace must contain an image content block"


def make_png_payload(
    idat_data: bytes,
    *,
    width: int = SCREEN_WIDTH,
    height: int = SCREEN_HEIGHT,
    bit_depth: int = 8,
    color_type: int = 2,
) -> str:
    """Build a CRC-correct PNG container with caller-controlled dimensions."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat_data)
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode("ascii")


_VALID_SCREENSHOT_PAYLOAD: str | None = None


def valid_screenshot_payload() -> str:
    """Generate a compact, structurally valid 800x600 RGB PNG for tests."""
    global _VALID_SCREENSHOT_PAYLOAD
    if _VALID_SCREENSHOT_PAYLOAD is None:
        scanline = b"\x00" + bytes(SCREEN_WIDTH * 3)
        raw = scanline * SCREEN_HEIGHT
        _VALID_SCREENSHOT_PAYLOAD = make_png_payload(zlib.compress(raw))
    return _VALID_SCREENSHOT_PAYLOAD


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
            json.dumps({"saved": True, "text": TARGET, "current_text": TARGET}),
            encoding="utf-8",
        )

        valid_trace = transcript(commands)
        assert grade(task, workspace, valid_trace) == 1.0

        # A correct earlier save is insufficient if the visible editor is
        # subsequently changed without another Save callback.
        post_save_edit = transcript(commands + (
            "desktopctl click 320 180",
            "desktopctl key End",
            "desktopctl key BackSpace",
        ))
        state_path.write_text(
            json.dumps({"saved": True, "text": TARGET, "current_text": TARGET[:-1]}),
            encoding="utf-8",
        )
        assert grade(task, workspace, post_save_edit) == 0.0
        state_path.write_text(
            json.dumps({"saved": True, "text": TARGET, "current_text": TARGET}),
            encoding="utf-8",
        )

        # A fully valid but tiny PNG must not satisfy the desktop screenshot gate.
        tiny_screenshot = transcript(commands)
        replace_image_payload(
            tiny_screenshot,
            make_png_payload(zlib.compress(b"\x00\x00\x00\x00"), width=1, height=1),
        )
        assert grade(task, workspace, tiny_screenshot) == 0.0
        assert _evidence(tiny_screenshot)[3]

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

        # A non-empty image block must contain real, structurally valid PNG bytes.
        malformed_base64 = transcript(commands)
        replace_image_payload(malformed_base64, "not-base64!")
        assert grade(task, workspace, malformed_base64) == 0.0
        assert _evidence(malformed_base64)[3]

        valid_base64_non_png = transcript(commands)
        replace_image_payload(valid_base64_non_png, "bm90IGEgcG5n")  # base64("not a png")
        assert grade(task, workspace, valid_base64_non_png) == 0.0
        assert _evidence(valid_base64_non_png)[3]

        invalid_crc = transcript(commands)
        png_bytes = bytearray(base64.b64decode(valid_screenshot_payload(), validate=True))
        png_bytes[-13] ^= 1  # corrupt the IDAT CRC while preserving the PNG signature/header
        replace_image_payload(invalid_crc, base64.b64encode(png_bytes).decode("ascii"))
        assert grade(task, workspace, invalid_crc) == 0.0
        assert _evidence(invalid_crc)[3]

        # CRC-valid chunk framing is not enough: the IDAT zlib stream and
        # decompressed scanline length must also be valid.
        invalid_deflate = transcript(commands)
        replace_image_payload(invalid_deflate, make_png_payload(b"not-a-zlib-stream"))
        assert grade(task, workspace, invalid_deflate) == 0.0
        assert _evidence(invalid_deflate)[3]

        invalid_ihdr = transcript(commands)
        replace_image_payload(
            invalid_ihdr,
            make_png_payload(zlib.compress(b"\x00\x00\x00\x00"), bit_depth=0, color_type=99),
        )
        assert grade(task, workspace, invalid_ihdr) == 0.0
        assert _evidence(invalid_ihdr)[3]

        wrong_scanline_length = transcript(commands)
        replace_image_payload(wrong_scanline_length, make_png_payload(zlib.compress(b"\x00\x00")))
        assert grade(task, workspace, wrong_scanline_length) == 0.0
        assert _evidence(wrong_scanline_length)[3]

        # A PNG filter byte outside the defined 0..4 range is not decodable evidence.
        invalid_filter = transcript(commands)
        first_row = b"\x05" + bytes(SCREEN_WIDTH * 3)
        remaining_rows = (b"\x00" + bytes(SCREEN_WIDTH * 3)) * (SCREEN_HEIGHT - 1)
        invalid_scanlines = first_row + remaining_rows
        replace_image_payload(invalid_filter, make_png_payload(zlib.compress(invalid_scanlines)))
        assert grade(task, workspace, invalid_filter) == 0.0
        assert _evidence(invalid_filter)[3]

        wrong_image_mime = transcript(commands)
        replace_image_payload(
            wrong_image_mime,
            valid_screenshot_payload(),
            mime_type="image/jpeg",
        )
        assert grade(task, workspace, wrong_image_mime) == 0.0
        assert _evidence(wrong_image_mime)[3]

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
        assert _evidence(shell_substitution)[3]

        # The verifier must reject shell expansion even when the first tokens
        # still look like an allowed desktopctl GUI action.
        shell_action_substitution = transcript((
            "desktopctl observe /tmp/before.png",
            "desktopctl click $(printf 320) 180",
            *commands[2:],
        ))
        assert grade(task, workspace, shell_action_substitution) == 0.0
        assert _evidence(shell_action_substitution)[3]

        shell_redirection = transcript((
            *commands[:-1],
            "desktopctl click 320 330 >/tmp/out",
        ))
        assert grade(task, workspace, shell_redirection) == 0.0
        assert _evidence(shell_redirection)[3]

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
