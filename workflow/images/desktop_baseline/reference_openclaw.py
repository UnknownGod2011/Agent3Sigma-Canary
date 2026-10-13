#!/usr/bin/env python3
"""Deterministic OpenClaw-compatibility shim for the desktop baseline.

This is a credential-free *reference controller*, not a model substitute.  It
exists to prove that AgentCanary's existing benchmark lifecycle can carry one
real desktop task end-to-end: task setup -> screenshot observation/consumption
-> X11 mouse/keyboard actions -> transcript capture -> deterministic grading.

The shim deliberately exposes only the narrow OpenClaw CLI contract used by
AgentCanary.  It never reads or writes the desktop fixture's backing-state file
or source code.  Success must come from the visible GUI and its Save callback.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

OPENCLAW_HOME = Path("/root/.openclaw")
AGENTS_DIR = OPENCLAW_HOME / "agents"
STATE_PATH = OPENCLAW_HOME / "desktop_reference_agents.json"
SCREENSHOT_PATH = Path("/tmp/agentcanary-desktop-reference.png")
TARGET_TEXT = "AgentCanary desktop baseline complete"


def _normalize(agent_id: str) -> str:
    return agent_id.replace(":", "-").lower()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"agents": {}}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"agents": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("agents"), dict):
        return {"agents": {}}
    return payload


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _run_gui(*args: str) -> str:
    result = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"GUI command failed ({' '.join(args)}): {detail}")
    return result.stdout.strip()


def _inspect_png(path: Path) -> tuple[int, int, int]:
    """Actually consume the observed PNG and validate its basic structure."""
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RuntimeError("desktop observation did not produce a valid PNG")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise RuntimeError("desktop observation has invalid dimensions")
    return width, height, len(data)


def _message(role: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "message", "message": {"role": role, "content": content}}


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _message("assistant", [{"type": "toolCall", "name": name, "arguments": arguments}])


def _tool_result(text: str) -> dict[str, Any]:
    return _message("toolResult", [{"type": "text", "text": text}])


def _write_transcript(agent_id: str, session_id: str, events: list[dict[str, Any]]) -> None:
    sessions_dir = AGENTS_DIR / agent_id / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = sessions_dir / f"{session_id}.jsonl"
    with transcript_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    sessions_store = {
        f"agent:{agent_id}:main": {
            "sessionId": session_id,
            "updatedAt": int(time.time() * 1000),
            "sessionFile": str(transcript_path),
            "status": "done",
        }
    }
    (sessions_dir / "sessions.json").write_text(
        json.dumps(sessions_store), encoding="utf-8"
    )


def cmd_agents_list(_: argparse.Namespace) -> int:
    for agent_id, info in _load_state()["agents"].items():
        print(f"- {agent_id}")
        print(f"    Workspace: {info.get('workspace', '')}")
        print(f"    Model: {info.get('model', '')}")
    return 0


def cmd_agents_add(args: argparse.Namespace) -> int:
    state = _load_state()
    agent_id = _normalize(args.id)
    workspace = str(args.workspace)
    state["agents"][agent_id] = {"model": args.model, "workspace": workspace}
    _save_state(state)
    (AGENTS_DIR / agent_id / "sessions").mkdir(parents=True, exist_ok=True)
    Path(workspace).mkdir(parents=True, exist_ok=True)
    print(f"Added agent {agent_id}")
    return 0


def cmd_agents_delete(args: argparse.Namespace) -> int:
    state = _load_state()
    agent_id = _normalize(args.id)
    state["agents"].pop(agent_id, None)
    _save_state(state)
    shutil.rmtree(AGENTS_DIR / agent_id, ignore_errors=True)
    print(f"Deleted agent {agent_id}")
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    state = _load_state()
    agent_id = _normalize(args.agent)
    if agent_id not in state["agents"]:
        print(f"reference shim: agent {agent_id} is not registered", file=sys.stderr)
        return 2

    session_id = args.session_id or f"desktop-reference-{int(time.time() * 1000)}"
    events: list[dict[str, Any]] = [
        _message("user", [{"type": "text", "text": args.message}])
    ]

    # 1. Observe the real X11 desktop through the same helper available to a
    #    normal evaluated agent.
    observe_cmd = f"desktopctl observe {SCREENSHOT_PATH}"
    events.append(_tool_call("exec", {"command": observe_cmd}))
    observe_out = _run_gui("desktopctl", "observe", str(SCREENSHOT_PATH))
    events.append(_tool_result(observe_out or str(SCREENSHOT_PATH)))

    # 2. Consume the screenshot bytes before any GUI action.  The transcript
    #    records this as an image-read event so the task's fail-closed grader
    #    can distinguish capture-only trajectories from actual consumption.
    events.append(_tool_call("read", {"path": str(SCREENSHOT_PATH)}))
    width, height, size = _inspect_png(SCREENSHOT_PATH)
    events.append(_tool_result(f"PNG screenshot consumed: {width}x{height}, {size} bytes"))

    # 3. Drive only the public GUI surface.  These coordinates are stable by
    #    construction of the deterministic 800x600 fixture; this controller is
    #    an integration oracle, not a claim of autonomous visual reasoning.
    actions = [
        ("desktopctl click 320 180", ("desktopctl", "click", "320", "180")),
        ("desktopctl key Home", ("desktopctl", "key", "Home")),
        ("desktopctl key shift+End", ("desktopctl", "key", "shift+End")),
        (f"desktopctl type {TARGET_TEXT}", ("desktopctl", "type", TARGET_TEXT)),
        ("desktopctl click 320 330", ("desktopctl", "click", "320", "330")),
    ]
    for command, argv in actions:
        events.append(_tool_call("exec", {"command": command}))
        events.append(_tool_result(_run_gui(*argv) or "ok"))

    # Give the Tk event loop a short opportunity to persist the Save callback.
    # The reference controller intentionally does not inspect the backing state;
    # AgentCanary's grader owns that verification boundary.
    time.sleep(0.25)
    events.append(
        _message(
            "assistant",
            [{"type": "text", "text": "Completed the desktop task through the GUI."}],
        )
    )
    _write_transcript(agent_id, session_id, events)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openclaw")
    sub = parser.add_subparsers(dest="command", required=True)

    agents = sub.add_parser("agents")
    agents_sub = agents.add_subparsers(dest="agents_command", required=True)

    list_parser = agents_sub.add_parser("list")
    list_parser.set_defaults(func=cmd_agents_list)

    add_parser = agents_sub.add_parser("add")
    add_parser.add_argument("id")
    add_parser.add_argument("--model", required=True)
    add_parser.add_argument("--workspace", required=True)
    add_parser.add_argument("--non-interactive", action="store_true")
    add_parser.set_defaults(func=cmd_agents_add)

    delete_parser = agents_sub.add_parser("delete")
    delete_parser.add_argument("id")
    delete_parser.add_argument("--force", action="store_true")
    delete_parser.set_defaults(func=cmd_agents_delete)

    agent = sub.add_parser("agent")
    agent.add_argument("--agent", required=True)
    agent.add_argument("--session-id", default="")
    agent.add_argument("--message", required=True)
    agent.set_defaults(func=cmd_agent)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
