#!/usr/bin/env python3
"""Unit checks for the credential-free OpenClaw desktop model stub."""
from __future__ import annotations

import json

from desktop_model_stub import TOOL_STEPS, completion_for_messages, stream_chunks


def _history(tool_calls: int, *, screenshot_image: bool = False) -> list[dict]:
    messages = [{"role": "user", "content": "Complete the desktop notes task."}]
    for index in range(tool_calls):
        call_id = f"call-{index}"
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": "exec", "arguments": "{}"},
            }],
        })
        content = "tool completed"
        if screenshot_image and index == 1:
            content = [
                {"type": "text", "text": "Screenshot read"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ]
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
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

    for index, (expected_name, expected_args) in enumerate(expected):
        messages = _history(index, screenshot_image=index >= 2)
        if index == 2:
            try:
                completion_for_messages(_history(index), created=1)
            except ValueError as exc:
                assert "screenshot image payload" in str(exc)
            else:
                raise AssertionError("stub must not issue GUI action without screenshot payload")
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
    print("desktop model stub tests passed: ordered GUI tools, screenshot-payload gate, and streaming responses")


if __name__ == "__main__":
    main()
