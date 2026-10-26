#!/usr/bin/env python3
"""Credential-free OpenAI-compatible provider stub for desktop integration CI.

This is a deterministic tool-loop fixture, not an autonomous model. It exercises
the installed OpenClaw CLI and refuses the first GUI action unless a valid
800x600 PNG screenshot payload appears in the provider request.
"""
from __future__ import annotations

import base64
import binascii
import json
import struct
import time
import zlib
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


def _valid_png_bytes(image_bytes: bytes) -> bool:
    """Accept only a decodable, CRC-checked 800x600 RGB/RGBA PNG screenshot."""
    if (
        not image_bytes
        or len(image_bytes) > 8 * 1024 * 1024
        or image_bytes[:8] != b"\x89PNG\r\n\x1a\n"
    ):
        return False

    offset = 8
    seen_ihdr = False
    seen_idat = False
    idat_ended = False
    seen_iend = False
    idat_data = bytearray()
    width = height = bit_depth = color_type = None
    chunks_seen = 0

    while offset < len(image_bytes):
        chunks_seen += 1
        if chunks_seen > 10000 or offset + 12 > len(image_bytes):
            return False
        chunk_length = struct.unpack(">I", image_bytes[offset:offset + 4])[0]
        chunk_type = image_bytes[offset + 4:offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(image_bytes):
            return False
        chunk_data = image_bytes[offset + 8:offset + 8 + chunk_length]
        stored_crc = struct.unpack(">I", image_bytes[offset + 8 + chunk_length:chunk_end])[0]
        if (zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF) != stored_crc:
            return False
        if (
            len(chunk_type) != 4
            or not all((65 <= byte <= 90) or (97 <= byte <= 122) for byte in chunk_type)
            or chunk_type[2] & 0x20
        ):
            return False

        if not seen_ihdr:
            if chunk_type != b"IHDR" or chunk_length != 13:
                return False
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if (
                width != 800
                or height != 600
                or bit_depth != 8
                or color_type not in (2, 6)
                or compression != 0
                or filter_method != 0
                or interlace != 0
            ):
                return False
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            return False

        if chunk_type == b"IDAT":
            if idat_ended:
                return False
            seen_idat = True
            idat_data.extend(chunk_data)
        elif seen_idat:
            idat_ended = True

        if chunk_type not in {b"IHDR", b"IDAT", b"IEND", b"PLTE"}:
            # Unknown critical chunks can change how pixels must be decoded.
            if not (chunk_type[0] & 0x20):
                return False

        if chunk_type == b"IEND":
            if chunk_length != 0 or not seen_idat:
                return False
            seen_iend = True
            offset = chunk_end
            break
        offset = chunk_end

    if not (
        seen_ihdr
        and seen_idat
        and seen_iend
        and offset == len(image_bytes)
        and idat_data
    ):
        return False

    channels = 3 if color_type == 2 else 4
    row_bytes = width * channels
    expected_size = (row_bytes + 1) * height
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(idat_data), expected_size + 1)
        if (
            len(raw) != expected_size
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or decoder.flush()
        ):
            return False
    except zlib.error:
        return False

    stride = row_bytes + 1
    return all(raw[row * stride] <= 4 for row in range(height))


def _valid_png_base64(data: Any) -> bool:
    if not isinstance(data, str) or not data or len(data) > 12 * 1024 * 1024:
        return False
    try:
        image_bytes = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        return False
    return _valid_png_bytes(image_bytes)


def _valid_png_data_url(url: str) -> bool:
    header, separator, payload = url.partition(",")
    return bool(
        separator
        and header.lower() == "data:image/png;base64"
        and _valid_png_base64(payload)
    )


def contains_image_payload(value: Any) -> bool:
    """Require actual decodable screenshot bytes, not just an image MIME label."""
    if isinstance(value, dict):
        image_url = value.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url")
            if isinstance(url, str) and _valid_png_data_url(url):
                return True
        url = value.get("url")
        if isinstance(url, str) and _valid_png_data_url(url):
            return True
        data = value.get("data")
        mime = value.get("mimeType") or value.get("mime_type") or value.get("media_type")
        if isinstance(mime, str) and mime.lower() == "image/png" and _valid_png_base64(data):
            return True
        source = value.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            if (
                str(source.get("media_type", "")).lower() == "image/png"
                and _valid_png_base64(source.get("data"))
            ):
                return True
        return any(contains_image_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_image_payload(item) for item in value)
    return isinstance(value, str) and _valid_png_data_url(value)


def tool_call_count(messages: list[dict[str, Any]]) -> int:
    return sum(
        1 for message in messages
        if isinstance(message, dict)
        and message.get("role") == "assistant"
        and isinstance(message.get("tool_calls"), list)
        and bool(message["tool_calls"])
    )


def screenshot_read_response_has_image(messages: list[dict[str, Any]]) -> bool:
    """Require a valid screenshot in the tool result for the second tool call.

    The deterministic plan's second call is the screenshot-reading `read`
    operation. Inspect only its matching tool result; images elsewhere in the
    conversation must not satisfy this gate.
    """
    seen_calls = 0
    read_call_id = None
    read_call_index = -1
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            seen_calls += 1
            if seen_calls == 2:
                read_call_id = call.get("id")
                read_call_index = message_index
                break
        if read_call_id is not None:
            break

    if not isinstance(read_call_id, str) or not read_call_id:
        return False
    matching_results = [
        message
        for index, message in enumerate(messages)
        if index > read_call_index
        and isinstance(message, dict)
        and message.get("role") == "tool"
        and message.get("tool_call_id") == read_call_id
    ]
    return len(matching_results) == 1 and contains_image_payload(
        matching_results[0].get("content")
    )


def completion_for_messages(messages: list[dict[str, Any]], *, created: int | None = None) -> dict[str, Any]:
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    step = tool_call_count(messages)
    if step == 2 and not screenshot_read_response_has_image(messages):
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
    chunks = [{"id": base["id"], "object": base["object"], "created": base["created"], "model": base["model"],
               "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}]
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
