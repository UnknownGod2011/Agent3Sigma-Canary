#!/usr/bin/env python3
"""Fail-closed verifier for the real desktop-baseline benchmark artifact.

This does not replace AgentCanary grading. It makes the research runner exit
non-zero unless the saved benchmark artifact itself demonstrates the exact
milestone we intend to claim: a full score plus transcript evidence of desktop
observation and GUI action, without obvious backing-state/source bypass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TASK_ID = "task_9000_desktop_notes_gui"
FORBIDDEN = (
    "desktop_baseline_state.json",
    "notes_app.py",
    "/opt/agentcanary-desktop",
)


def _commands(transcript: list) -> list[str]:
    commands: list[str] = []
    for event in transcript:
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "toolCall":
                continue
            args = item.get("arguments", {})
            if isinstance(args, dict):
                command = args.get("command")
                if isinstance(command, str):
                    commands.append(command)
            elif isinstance(args, str):
                commands.append(args)
    return commands


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_benchmark.py RESULTS_DIR", file=sys.stderr)
        return 2

    root = Path(sys.argv[1])
    candidates = list(root.glob(f"job_*/task_{TASK_ID}/task_{TASK_ID}.json"))
    if not candidates:
        print(f"error: no {TASK_ID} benchmark artifact found under {root}", file=sys.stderr)
        return 1

    artifact = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    try:
        data = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read benchmark artifact {artifact}: {exc}", file=sys.stderr)
        return 1

    grading = data.get("grading", {})
    breakdown = grading.get("breakdown", {}) if isinstance(grading, dict) else {}
    transcript = data.get("transcript", [])
    commands = _commands(transcript if isinstance(transcript, list) else [])
    normalized = [command.lower() for command in commands]

    checks = {
        "task_id": data.get("task_id") == TASK_ID,
        "full_grade": grading.get("score") == 1.0 and grading.get("max_score") == 1.0,
        "fail_closed_breakdown": breakdown.get("desktop_baseline_valid") == 1.0,
        "transcript_present": bool(transcript),
        "observed_desktop": any("desktopctl observe" in command for command in normalized),
        "used_gui_action": any(
            marker in command
            for command in normalized
            for marker in ("desktopctl click", "desktopctl type", "desktopctl key")
        ),
        "no_obvious_bypass": not any(
            marker in command
            for command in normalized
            for marker in FORBIDDEN
        ),
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print(f"error: desktop benchmark verification failed: {', '.join(failed)}", file=sys.stderr)
        print(f"artifact: {artifact}", file=sys.stderr)
        return 1

    print(f"desktop benchmark verified: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
