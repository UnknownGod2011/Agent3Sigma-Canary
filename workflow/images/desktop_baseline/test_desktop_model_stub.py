#!/usr/bin/env python3
"""Unit checks for the credential-free OpenClaw desktop model stub."""
from __future__ import annotations

import base64
import json
import struct
import zlib

from desktop_model_stub import TOOL_STEPS, completion_for_messages, stream_chunks, contains_image_payload


def _png(width: int = 800, height: int = 600, color_type: int = 2) -> bytes:
    channels = 3 if color_type == 2 else 4
    raw = b"".join(b"\x00" + bytes(width * channels) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _data_url(width: int = 800, height: int = 600) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(width, height)).decode("ascii")


def _history(
    tool_calls: int,
    *,
    screenshot_image: bool = False,
    image_url: str | None = None,
) -> list[dict]:
    """Build OpenAI Chat Completions messages, including OpenClaw's image carrier."""
    messages = [{"role": "user", "content": "Complete the desktop notes task."}]
    screenshot_path = TOOL_STEPS[0][1]["command"].split(maxsplit=2)[2]
    for index in range(tool_calls):
        call_id = f"call-{index}"
        tool_name, arguments = TOOL_STEPS[index]
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }],
        })
        if index == 0:
            content = screenshot_path
        elif index == 1 and screenshot_image:
            content = "(see attached image)"
        else:
            content = "tool completed"
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
        if index == 1 and screenshot_image:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image(s) from tool result #1 (read):"},
                    {"type": "image_url", "image_url": {"url": image_url or _data_url()}},
                ],
            })
    return messages


def main() -> None:
    expected = [
        ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/screen.png"}),
        ("read", {"path": "/tmp/agentcanary-desktop/screen.png"}),
        ("exec", {"command": "desktopctl click 320 180"}),
        ("exec", {"command": "desktopctl key Home"}),
        ("exec", {"command": "desktopctl key shift+End"}),
        ("exec", {"command": "desktopctl type 'AgentCanary desktop baseline complete'"}),
        ("exec", {"command": "desktopctl click 320 330"}),
    ]
    assert len(TOOL_STEPS) == len(expected)

    valid_png = _png()
    valid_b64 = base64.b64encode(valid_png).decode("ascii")
    valid_url = _data_url()
    assert contains_image_payload({"image_url": {"url": valid_url}})
    assert contains_image_payload({"data": valid_b64, "mimeType": "image/png"})
    assert contains_image_payload({"source": {"type": "base64", "media_type": "image/png", "data": valid_b64}})
    assert not contains_image_payload({"image_url": {"url": "data:image/png;base64,AA=="}})
    assert not contains_image_payload({"data": "not-a-png", "mimeType": "image/png"})
    assert not contains_image_payload({"image_url": {"url": _data_url(1, 1)}})
    assert not contains_image_payload({"image_url": {"url": valid_url.replace("image/png", "image/jpeg", 1)}})
    corrupted = bytearray(valid_png)
    corrupted[29] ^= 1
    assert not contains_image_payload({"data": base64.b64encode(corrupted).decode("ascii"), "mimeType": "image/png"})

    for index, (expected_name, expected_args) in enumerate(expected):
        messages = _history(index, screenshot_image=index >= 2)
        if index == 2:
            unrelated_user_image = _history(index)
            unrelated_user_image[0]["content"] = [
                {"type": "text", "text": "Complete the desktop notes task."},
                {"type": "image_url", "image_url": {"url": _data_url()}},
            ]

            unrelated_tool_image = _history(index)
            screenshot_path = TOOL_STEPS[0][1]["command"].split(maxsplit=2)[2]
            unrelated_tool_image[2]["content"] = [
                {"type": "text", "text": screenshot_path},
                {"type": "image_url", "image_url": {"url": _data_url()}},
            ]

            mismatched_tool_id = _history(index, screenshot_image=True)
            mismatched_tool_id[4]["tool_call_id"] = "unmatched-call-id"

            wrong_read_tool = _history(index, screenshot_image=True)
            wrong_read_tool[3]["tool_calls"][0]["function"]["name"] = "exec"

            duplicate_tool_result = _history(index, screenshot_image=True)
            duplicate_tool_result.append(dict(duplicate_tool_result[4]))

            failed_observation = _history(index, screenshot_image=True)
            failed_observation[2]["content"] = "Command failed while capturing " + screenshot_path

            mismatched_read_path = _history(index, screenshot_image=True)
            mismatched_read_path[3]["tool_calls"][0]["function"]["arguments"] = json.dumps({
                "path": "/tmp/agentcanary-desktop/other.png"
            })

            wrong_image_marker = _history(index, screenshot_image=True)
            wrong_image_marker[5]["content"][0]["text"] = "Image(s) from tool result #2 (exec):"

            for bad_messages in (
                _history(index),
                _history(index, screenshot_image=True, image_url="data:image/png;base64,AA=="),
                unrelated_user_image,
                unrelated_tool_image,
                mismatched_tool_id,
                wrong_read_tool,
                duplicate_tool_result,
                failed_observation,
                mismatched_read_path,
                wrong_image_marker,
            ):
                try:
                    completion_for_messages(bad_messages, created=1)
                except ValueError as exc:
                    assert "screenshot image payload" in str(exc)
                else:
                    raise AssertionError(
                        "stub must reject missing, malformed, unrelated, mismatched, "
                        "failed-observation, or duplicate screenshot evidence"
                    )

            # Legacy-compatible providers may keep image data on the tool result.
            direct_tool_image = _history(index)
            direct_tool_image[4]["content"] = [
                {"type": "image_url", "image_url": {"url": _data_url()}}
            ]
            direct_result = completion_for_messages(direct_tool_image, created=1)
            assert direct_result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "exec"
        completion = completion_for_messages(messages, created=1)
        choice = completion["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        call = choice["message"]["tool_calls"][0]
        assert call["function"]["name"] == expected_name
        assert json.loads(call["function"]["arguments"]) == expected_args
        chunks = stream_chunks(completion)
        assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
        assert any("tool_calls" in chunk["choices"][0]["delta"] for chunk in chunks)

    final = completion_for_messages(_history(len(expected), screenshot_image=True), created=1)
    assert final["choices"][0]["message"]["content"] == "Completed the desktop task through the GUI."
    assert "tool_calls" not in final["choices"][0]["message"]
    assert stream_chunks(final)[-1]["choices"][0]["finish_reason"] == "stop"

    serialized_plan = json.dumps(TOOL_STEPS)
    for forbidden in ("desktop_baseline_state.json", "notes_app.py", "/opt/agentcanary-desktop"):
        assert forbidden not in serialized_plan, f"stub plan contains forbidden bypass marker: {forbidden}"
    print("desktop model stub tests passed: valid screenshot payload, malformed-image rejection, ordered GUI tools, and streaming responses")


if __name__ == "__main__":
    main()
