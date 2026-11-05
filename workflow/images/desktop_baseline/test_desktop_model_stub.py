#!/usr/bin/env python3
"""Unit checks for the credential-free OpenClaw desktop model stub."""
from __future__ import annotations

import base64
import json
import struct
import zlib
from unittest.mock import patch

import desktop_model_stub as stub
from desktop_model_stub import (
    TOOL_STEPS,
    completion_for_messages,
    stream_chunks,
    contains_image_payload,
    screenshot_read_response_has_image,
)


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
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _data_url(width: int = 800, height: int = 600) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(width, height)).decode("ascii")


def _history_for_steps(
    steps: list[tuple[str, dict | None]],
    *,
    image_indices: tuple[int, ...] = (1, 7),
    image_url: str | None = None,
) -> list[dict]:
    """Build OpenAI Chat Completions history with correlated OpenClaw image carriers."""
    messages = [{"role": "user", "content": "Complete the desktop notes task."}]
    for index, (name, arguments) in enumerate(steps):
        if arguments is None:
            if index != 2:
                raise AssertionError(f"unexpected dynamic action in fixture plan at step {index}")
            arguments = {"command": "desktopctl click 124 152"}
        call_id = f"call-{index}"
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }],
        })
        if name == "exec" and arguments["command"].startswith("desktopctl observe "):
            result_content = arguments["command"].split(maxsplit=2)[2]
        else:
            result_content = "tool completed"
        messages.append({"role": "tool", "tool_call_id": call_id, "content": result_content})
        if name == "read" and index in image_indices:
            messages[-1]["content"] = "(see attached image)"
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Attached image(s) from tool result:"},
                    {"type": "image_url", "image_url": {"url": image_url or _data_url()}},
                ],
            })
    return messages


def _history(
    tool_calls: int,
    *,
    image_indices: tuple[int, ...] = (1, 7),
    image_url: str | None = None,
) -> list[dict]:
    steps = list(TOOL_STEPS)
    if tool_calls > len(steps):
        steps.append(("exec", {"command": "desktopctl click 359 334"}))
    return _history_for_steps(steps[:tool_calls], image_indices=image_indices, image_url=image_url)


def _next_tool(completion: dict) -> tuple[str, dict]:
    message = completion["choices"][0]["message"]
    call = message["tool_calls"][0]
    return call["function"]["name"], json.loads(call["function"]["arguments"])


def main() -> None:
    assert len(TOOL_STEPS) == 8
    valid_png = _png()
    valid_b64 = base64.b64encode(valid_png).decode("ascii")
    valid_url = _data_url()
    assert contains_image_payload({"image_url": {"url": valid_url}})
    assert contains_image_payload({"data": valid_b64, "mimeType": "image/png"})
    assert contains_image_payload({
        "source": {"type": "base64", "media_type": "image/png", "data": valid_b64}
    })
    assert not contains_image_payload({"image_url": {"url": "data:image/png;base64,AA=="}})
    assert not contains_image_payload({"data": "not-a-png", "mimeType": "image/png"})
    assert not contains_image_payload({"image_url": {"url": _data_url(1, 1)}})
    assert not contains_image_payload({
        "image_url": {"url": valid_url.replace("image/png", "image/jpeg", 1)}
    })
    corrupted = bytearray(valid_png)
    corrupted[29] ^= 1
    assert not contains_image_payload({
        "data": base64.b64encode(corrupted).decode("ascii"),
        "mimeType": "image/png",
    })

    static_expected = {
        0: ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/screen.png"}),
        1: ("read", {"path": "/tmp/agentcanary-desktop/screen.png"}),
        3: ("exec", {"command": "desktopctl key Home"}),
        4: ("exec", {"command": "desktopctl key shift+End"}),
        5: ("exec", {"command": "desktopctl type 'AgentCanary desktop baseline complete'"}),
        6: ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/save.png"}),
        7: ("read", {"path": "/tmp/agentcanary-desktop/save.png"}),
    }
    for step, expected in static_expected.items():
        assert _next_tool(completion_for_messages(_history(step), created=1)) == expected

    first_history = _history(2, image_indices=(1,))
    with patch.object(stub, "locate_text", return_value=(124, 152)) as locate:
        first = completion_for_messages(first_history, created=1)
    assert _next_tool(first) == ("exec", {"command": "desktopctl click 124 152"})
    locate.assert_called_once()
    assert screenshot_read_response_has_image(first_history)

    second_history = _history(8, image_indices=(1, 7))
    with patch.object(stub, "locate_text", return_value=(237, 153)) as locate, patch.object(
        stub, "locate_save_button", return_value=(359, 334)
    ) as locate_save:
        second = completion_for_messages(second_history, created=1)
    assert _next_tool(second) == ("exec", {"command": "desktopctl click 359 334"})
    assert locate.call_args.args[1] == "AgentCanary desktop baseline complete"
    locate_save.assert_called_once()
    assert screenshot_read_response_has_image(second_history)

    with patch.object(stub, "locate_text", side_effect=LookupError("target not visible")):
        retry_one = completion_for_messages(second_history, created=1)
    assert _next_tool(retry_one) == (
        "exec",
        {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-1.png"},
    )

    retry_one_steps = list(TOOL_STEPS) + [
        ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-1.png"}),
        ("read", {"path": "/tmp/agentcanary-desktop/verify-1.png"}),
    ]
    retry_one_history = _history_for_steps(retry_one_steps, image_indices=(1, 7, 9))
    with patch.object(stub, "locate_text", side_effect=LookupError("target not visible")):
        retry_two = completion_for_messages(retry_one_history, created=1)
    assert _next_tool(retry_two) == (
        "exec",
        {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-2.png"},
    )

    retry_two_steps = retry_one_steps + [
        ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-2.png"}),
        ("read", {"path": "/tmp/agentcanary-desktop/verify-2.png"}),
    ]
    retry_two_history = _history_for_steps(retry_two_steps, image_indices=(1, 7, 9, 11))
    with patch.object(stub, "locate_text", side_effect=LookupError("target not visible")):
        try:
            completion_for_messages(retry_two_history, created=1)
        except ValueError as exc:
            assert "refusing Save" in str(exc)
        else:
            raise AssertionError("the provider must fail closed after two re-observations")

    with patch.object(stub, "locate_text", return_value=(237, 153)) as locate, patch.object(
        stub, "locate_save_button", return_value=(359, 334)
    ) as locate_save:
        retry_two_visible = completion_for_messages(retry_two_history, created=1)
    assert _next_tool(retry_two_visible) == ("exec", {"command": "desktopctl click 359 334"})
    assert locate.call_args.args[1] == "AgentCanary desktop baseline complete"
    locate_save.assert_called_once()

    observe_one_steps = list(TOOL_STEPS) + [
        ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-1.png"}),
    ]
    assert _next_tool(completion_for_messages(_history_for_steps(observe_one_steps), created=1)) == (
        "read", {"path": "/tmp/agentcanary-desktop/verify-1.png"}
    )

    observe_two_steps = retry_one_steps + [
        ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/verify-2.png"}),
    ]
    assert _next_tool(completion_for_messages(
        _history_for_steps(observe_two_steps, image_indices=(1, 7, 9)), created=1
    )) == ("read", {"path": "/tmp/agentcanary-desktop/verify-2.png"})

    try:
        completion_for_messages(_history(8, image_indices=(1,)), created=1)
    except ValueError as exc:
        assert "matching desktop screenshot" in str(exc)
    else:
        raise AssertionError("the Save click must require its own screenshot")

    malformed_or_unrelated = []
    missing_image = _history(2, image_indices=())
    unrelated_user_image = _history(2, image_indices=())
    unrelated_user_image[0]["content"] = [
        {"type": "text", "text": "Complete the desktop notes task."},
        {"type": "image_url", "image_url": {"url": _data_url()}},
    ]
    unrelated_tool_image = _history(2, image_indices=())
    unrelated_tool_image[2]["content"] = [
        {"type": "text", "text": "/tmp/agentcanary-desktop/screen.png"},
        {"type": "image_url", "image_url": {"url": _data_url()}},
    ]
    mismatched_tool_id = _history(2)
    mismatched_tool_id[4]["tool_call_id"] = "unmatched-call-id"
    wrong_read_tool = _history(2)
    wrong_read_tool[3]["tool_calls"][0]["function"]["name"] = "exec"
    duplicate_tool_result = _history(2)
    duplicate_tool_result.append(dict(duplicate_tool_result[4]))
    failed_observation = _history(2)
    failed_observation[2]["content"] = "Command failed while capturing /tmp/agentcanary-desktop/screen.png"
    mismatched_read_path = _history(2)
    mismatched_read_path[3]["tool_calls"][0]["function"]["arguments"] = json.dumps({
        "path": "/tmp/agentcanary-desktop/other.png"
    })
    wrong_image_marker = _history(2)
    wrong_image_marker[5]["content"][0]["text"] = "Image(s) from tool result #2 (exec):"
    malformed_image_marker = _history(2)
    malformed_image_marker[5]["content"][0]["text"] = "Unrelated image(s) from tool result:"
    detached_image_carrier = _history(2)
    detached_image_carrier.insert(5, {"role": "user", "content": "Unrelated interstitial message."})
    malformed_or_unrelated.extend([
        missing_image,
        unrelated_user_image,
        unrelated_tool_image,
        mismatched_tool_id,
        wrong_read_tool,
        duplicate_tool_result,
        failed_observation,
        mismatched_read_path,
        wrong_image_marker,
        malformed_image_marker,
        detached_image_carrier,
        _history(2, image_indices=(1,), image_url="data:image/png;base64,AA=="),
    ])
    for bad_messages in malformed_or_unrelated:
        assert not screenshot_read_response_has_image(bad_messages)
        try:
            completion_for_messages(bad_messages, created=1)
        except ValueError as exc:
            assert "matching desktop screenshot" in str(exc)
        else:
            raise AssertionError("stub must reject unrelated or malformed screenshot evidence")

    direct_tool_image = _history(2, image_indices=())
    direct_tool_image[4]["content"] = [
        {"type": "image_url", "image_url": {"url": _data_url()}}
    ]
    assert screenshot_read_response_has_image(direct_tool_image)

    legacy_labeled_carrier = _history(2)
    legacy_labeled_carrier[5]["content"][0]["text"] = "Image(s) from tool result #1 (read):"
    assert screenshot_read_response_has_image(legacy_labeled_carrier)

    final = completion_for_messages(_history(9), created=1)
    assert final["choices"][0]["message"]["content"] == "Completed the desktop task through the GUI."
    assert "tool_calls" not in final["choices"][0]["message"]
    assert stream_chunks(final)[-1]["choices"][0]["finish_reason"] == "stop"

    serialized_plan = json.dumps(TOOL_STEPS)
    for forbidden in ("desktop_baseline_state.json", "notes_ui.py", "/opt/agentcanary-desktop"):
        assert forbidden not in serialized_plan, f"stub plan contains forbidden bypass marker: {forbidden}"
    print(
        "desktop model stub tests passed: both screenshot-grounded clicks, "
        "matching image carriers, malformed-image rejection, and streaming responses"
    )


if __name__ == "__main__":
    main()
