#!/usr/bin/env python3
"""Credential-free OpenAI-compatible provider stub for desktop integration CI.

This is a deterministic tool-loop fixture, not an autonomous model. It exercises
the installed OpenClaw CLI and refuses the first GUI action unless the screenshot
image payload appears in the provider request.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
PORT = 8765
MODEL_ID = "desktop-fixture"
API_KEY = "agentcanary-local-stub-key"

TOOL_STEPS: tuple[tuple[str, dict[str, str]], ...] = (
    ("exec", {"command": "desktopctl observe /tmp/agentcanary-desktop/screen.png"}),
    ("read", {"path": "/tmp/agentcanary-desktop/screen.png"}),
    ("exec", {"command": "desktopctl click 320 180"}),
    ("exec", {"command": "desktopctl key Home"}),
    ("exec", {"command": "desktopctl key shift+End"}),
    ("exec", {"command": "desktopctl type 'AgentCanary desktop baseline complete'"}),
    ("exec", {"command": "desktopctl click 320 330"}),
)


def contains_image_payload(value: Any) -> bool:
    """Require actual image bytes encoded as a data URL or typed base64 part."""
    if isinstance(value, dict):
        image_url = value.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url")
            if isinstance(url, str) and url.startswith("data:image/"):
                return True
        url = value.get("url")
        if isinstance(url, str) and url.startswith("data:image/"):
            return True
        data = value.get("data")
        mime = value.get("mimeType") or value.get("mime_type") or value.get("media_type")
        if isinstance(data, str) and isinstance(mime, str) and mime.startswith("image/"):
            return True
        source = value.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            if isinstance(source.get("data"), str) and str(source.get("media_type", "")).startswith("image/"):
                return True
        return any(contains_image_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_image_payload(item) for item in value)
    return isinstance(value, str) and value.startswith("data:image/")


def tool_call_count(messages: list[dict[str, Any]]) -> int:
    return sum(
        1 for message in messages
        if isinstance(message, dict)
        and message.get("role") == "assistant"
        and isinstance(message.get("tool_calls"), list)
        and bool(message["tool_calls"])
    )


def completion_for_messages(messages: list[dict[str, Any]], *, created: int | None = None) -> dict[str, Any]:
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    step = tool_call_count(messages)
    if step == 2 and not contains_image_payload(messages):
        raise ValueError("screenshot image payload was not returned to the model before GUI action")
    response: dict[str, Any] = {
        "id": f"chatcmpl-desktop-stub-{step}",
        "object": "chat.completion",
        "created": int(time.time()) if created is None else created,
        "model": MODEL_ID,
        "choices": [],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    if step < len(TOOL_STEPS):
        name, arguments = TOOL_STEPS[step]
        call = {
            "id": f"call_desktop_stub_{step}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, separators=(",", ":"))},
        }
        response["choices"] = [{
            "index": 0,
            "message": {"role": "assistant", "content": None, "tool_calls": [call]},
            "finish_reason": "tool_calls",
        }]
    else:
        response["choices"] = [{
            "index": 0,
            "message": {"role": "assistant", "content": "Completed the desktop task through the GUI."},
            "finish_reason": "stop",
        }]
    return response


def stream_chunks(completion: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a completion into OpenAI-compatible server-sent event chunks."""
    choice = completion["choices"][0]
    message = choice["message"]
    base = {
        "id": completion["id"],
        "object": "chat.completion.chunk",
        "created": completion["created"],
        "model": completion["model"],
    }
    chunks = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}]
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        call = tool_calls[0]
        chunks.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": call["id"], "type": "function",
            "function": {"name": call["function"]["name"]},
        }]}, "finish_reason": None}]})
        chunks.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "function": {"arguments": call["function"]["arguments"]},
        }]}, "finish_reason": None}]})
    else:
        chunks.append({**base, "choices": [{"index": 0, "delta": {"content": message.get("content", "")}, "finish_reason": None}]})
    chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]})
    return chunks


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[desktop-model-stub] " + (fmt % args), flush=True)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path.rstrip("/") == "/v1/models":
            self._send_json(200, {"object": "list", "data": [{
                "id": MODEL_ID, "object": "model", "created": 0, "owned_by": "agentcanary-test"
            }]})
        else:
            self._send_json(404, {"error": {"message": "not found", "type": "not_found_error"}})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send_json(404, {"error": {"message": "not found", "type": "not_found_error"}})
            return
        if self.headers.get("Authorization") != f"Bearer {API_KEY}":
            self._send_json(401, {"error": {"message": "invalid local test key", "type": "authentication_error"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8 * 1024 * 1024:
                raise ValueError("invalid request body length")
            request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request_payload, dict):
                raise ValueError("request body must be a JSON object")
            messages = request_payload.get("messages")
            if not isinstance(messages, list):
                raise ValueError("request messages must be a list")
            completion = completion_for_messages(messages)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return

        if request_payload.get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for chunk in stream_chunks(completion):
                    data = ("data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n").encode("utf-8")
                    self.wfile.write(data)
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self.close_connection = True
            return
        self._send_json(200, completion)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[desktop-model-stub] listening on http://{HOST}:{PORT}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
