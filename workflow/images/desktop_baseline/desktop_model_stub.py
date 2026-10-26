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


def _message_text(content: Any) -> str:
    """Extract text blocks from a provider-facing message without stringifying images."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        )
    return ""


def screenshot_read_response_has_image(messages: list[dict[str, Any]]) -> bool:
    """Require the observed screenshot to reach the provider before GUI input.

    OpenClaw's OpenAI Chat Completions adapter moves image blocks from a
    toolResult into a following user message labelled
    "Attached image(s) from tool result:". Also accept the legacy explicit
    "Image(s) from tool result #1 (read):" label, but only when it follows
    the matching read result. Require a successful observe and the exact same
    path for observe and read.
    """
    if not isinstance(messages, list):
        return False

    calls: list[tuple[int, Any, Any, dict[str, Any]]] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if not isinstance(function, dict):
                return False
            name = function.get("name")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    return False
            if not isinstance(arguments, dict):
                return False
            calls.append((message_index, call.get("id"), name, arguments))

    # This gate runs on the provider request after the second planned tool
    # call. The deterministic fixture intentionally emits one call per turn.
    if len(calls) != 2:
        return False

    observe_index, observe_id, observe_name, observe_args = calls[0]
    read_index, read_id, read_name, read_args = calls[1]
    observe_command = TOOL_STEPS[0][1]["command"]
    observe_prefix = "desktopctl observe "
    if not observe_command.startswith(observe_prefix):
        return False
    screenshot_path = observe_command[len(observe_prefix):]
    if (
        not screenshot_path
        or observe_name != "exec"
        or observe_args.get("command") != observe_command
        or read_name != "read"
        or read_args != {"path": screenshot_path}
        or not isinstance(observe_id, str)
        or not observe_id
        or not isinstance(read_id, str)
        or not read_id
        or observe_id == read_id
    ):
        return False

    observe_results = [
        (index, message)
        for index, message in enumerate(messages)
        if observe_index < index < read_index
        and isinstance(message, dict)
        and message.get("role") == "tool"
        and message.get("tool_call_id") == observe_id
    ]
    if (
        len(observe_results) != 1
        or _message_text(observe_results[0][1].get("content")).strip() != screenshot_path
    ):
        return False

    read_results = [
        (index, message)
        for index, message in enumerate(messages)
        if index > read_index
        and isinstance(message, dict)
        and message.get("role") == "tool"
        and message.get("tool_call_id") == read_id
    ]
    if len(read_results) != 1:
        return False

    read_result_index, read_result = read_results[0]
    read_content = read_result.get("content")
    # Some compatible providers preserve media on the tool result itself.
    if contains_image_payload(read_content):
        return True

    # OpenClaw's OpenAI Chat Completions adapter relocates tool-result images
    # into a user message. The marker binds this image carrier to the read
    # result above; an image elsewhere in history is not sufficient.
    next_assistant_index = next(
        (
            index
            for index in range(read_result_index + 1, len(messages))
            if isinstance(messages[index], dict)
            and messages[index].get("role") == "assistant"
        ),
        len(messages),
    )
    # The installed OpenClaw adapter emits a generic
    # "Attached image(s) from tool result:" carrier. Bind it by strict
    # adjacency to the uniquely correlated successful read result above. If an
    # adapter supplies an explicit source index, require the expected read label.
    carrier_index = read_result_index + 1
    if carrier_index >= next_assistant_index:
        return False
    carrier = messages[carrier_index]
    if not isinstance(carrier, dict) or carrier.get("role") != "user":
        return False
    content = carrier.get("content")
    marker_lines = [
        line.strip().lower()
        for line in _message_text(content).splitlines()
        if "image(s) from tool result" in line.lower()
    ]
    if len(marker_lines) != 1:
        return False
    marker = marker_lines[0]
    allowed_labels = {
        "attached image(s) from tool result:",
        "image(s) from tool result #1 (read):",
    }
    if marker not in allowed_labels:
        return False
    return contains_image_payload(content)


def _message_shape_summary(messages: list[dict[str, Any]]) -> list[list[Any]]:
    """Return compact structural diagnostics; never include prompts or image bytes."""
    expected_path = TOOL_STEPS[0][1]["command"].split(maxsplit=2)[2]
    summary: list[list[Any]] = []
    start_index = max(0, len(messages) - 6)
    for index, message in enumerate(messages[-6:], start=start_index):
        if not isinstance(message, dict):
            summary.append([index, "?", type(message).__name__])
            continue
        role = message.get("role")
        if role == "assistant":
            calls = []
            tool_calls = message.get("tool_calls")
            for call in tool_calls if isinstance(tool_calls, list) else []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except (json.JSONDecodeError, TypeError):
                        arguments = None
                short_id = str(call.get("id", ""))[-8:]
                if name == "exec" and isinstance(arguments, dict):
                    command = arguments.get("command")
                    tokens = command.split() if isinstance(command, str) else []
                    operation = tokens[1] if len(tokens) > 1 and tokens[0] == "desktopctl" else None
                    calls.append([short_id, name, operation])
                elif name == "read" and isinstance(arguments, dict):
                    calls.append([short_id, name, arguments.get("path") == expected_path])
                else:
                    calls.append([short_id, name])
            summary.append([index, "a", calls])
        elif role in {"tool", "user"}:
            content = message.get("content")
            kind = "s" if isinstance(content, str) else "l" if isinstance(content, list) else type(content).__name__
            has_png = contains_image_payload(content)
            text_content = _message_text(content)
            if role == "tool":
                summary.append([
                    index, "t", str(message.get("tool_call_id", ""))[-8:], kind,
                    has_png, text_content.strip() == expected_path,
                ])
            else:
                block_types = [
                    block.get("type", "?") if isinstance(block, dict) else type(block).__name__
                    for block in content
                ] if isinstance(content, list) else []
                marker = next(
                    (line[:48] for line in text_content.splitlines()
                     if "image(s) from tool result" in line.lower()),
                    "",
                )
                summary.append([index, "u", kind, block_types, has_png, marker])
        else:
            summary.append([index, str(role)[:8]])
    return summary


def completion_for_messages(messages: list[dict[str, Any]], *, created: int | None = None) -> dict[str, Any]:
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    step = tool_call_count(messages)
    if step == 2 and not screenshot_read_response_has_image(messages):
        raise ValueError(
            "screenshot image payload was not returned to the model before GUI action; wire_shape="
            + json.dumps(_message_shape_summary(messages), separators=(",", ":"))
        )
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
