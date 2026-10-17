#!/usr/bin/env python3
"""Fail-closed verifier for the real desktop-baseline benchmark artifact.

This does not replace AgentCanary grading. It makes the research runner exit
non-zero unless the saved AgentCanary result contains a full score and an
ordered trajectory: observe a screenshot, read that exact screenshot, then act
through GUI input, without obvious backing-state or fixture-source access.
"""
from __future__ import annotations

import json
import posixpath
import shlex
import sys
from pathlib import Path

TASK_ID = "task_9000_desktop_notes_gui"
DEFAULT_SCREENSHOT = "/tmp/agentcanary-desktop/screen.png"
FORBIDDEN = (
    "desktop_baseline_state.json",
    "notes_app.py",
    "/opt/agentcanary-desktop",
)


def _command_segments(command: str) -> list[list[str]]:
    # Only count literal top-level desktopctl invocations as GUI evidence.
    segments = []
    start = 0
    quote = None
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char in {";", "&", "|", "\n"}:
            raw = command[start:index].strip()
            if raw:
                try:
                    tokens = shlex.split(raw)
                except ValueError:
                    tokens = []
                if tokens:
                    segments.append(tokens)
            if char in {"&", "|"} and index + 1 < len(command) and command[index + 1] == char:
                index += 1
            start = index + 1
        index += 1
    raw = command[start:].strip()
    if raw:
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = []
        if tokens:
            segments.append(tokens)
    return segments


def _observed_path(command: str) -> str | None:
    for tokens in _command_segments(command):
        if len(tokens) >= 2 and Path(tokens[0]).name == "desktopctl" and tokens[1] == "observe":
            if len(tokens) >= 3 and not tokens[2].startswith(("<", ">")):
                return posixpath.normpath(tokens[2])
            return DEFAULT_SCREENSHOT
    return None
def _evidence(transcript: list) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[tuple[int, str]], bool]:
    observations: list[tuple[int, str]] = []
    image_reads: list[tuple[int, str]] = []
    gui_actions: list[tuple[int, str]] = []
    bypassed = False
    sequence = 0

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
            args_text = json.dumps(args, ensure_ascii=False).lower()
            if any(marker in args_text for marker in FORBIDDEN):
                bypassed = True

            if isinstance(args, dict):
                command = args.get("command")
                if isinstance(command, str):
                    path = _observed_path(command)
                    if path is not None:
                        observations.append((sequence, path))
                    if any(
                        len(tokens) >= 2
                        and Path(tokens[0]).name == "desktopctl"
                        and tokens[1] in {"click", "type", "key"}
                        for tokens in _command_segments(command)
                    ):
                        gui_actions.append((sequence, command))

                path = args.get("path")
                if item.get("name") == "read" and isinstance(path, str):
                    image_reads.append((sequence, posixpath.normpath(path)))

            sequence += 1

    return observations, image_reads, gui_actions, bypassed


def _inspected_before_action(
    observations: list[tuple[int, str]],
    image_reads: list[tuple[int, str]],
    gui_actions: list[tuple[int, str]],
) -> bool:
    first_action = min((index for index, _ in gui_actions), default=None)
    if first_action is None:
        return False
    return any(
        observation_index < read_index < first_action
        and observation_path == read_path
        and read_path.lower().endswith(".png")
        for observation_index, observation_path in observations
        for read_index, read_path in image_reads
    )


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
    if not isinstance(data, dict):
        print(f"error: benchmark artifact root must be a JSON object: {artifact}", file=sys.stderr)
        return 1

    grading = data.get("grading", {})
    if not isinstance(grading, dict):
        grading = {}
    breakdown = grading.get("breakdown", {})
    if not isinstance(breakdown, dict):
        breakdown = {}
    transcript = data.get("transcript", [])
    if not isinstance(transcript, list):
        transcript = []

    observations, image_reads, gui_actions, bypassed = _evidence(transcript)
    checks = {
        "task_id": data.get("task_id") == TASK_ID,
        "full_grade": grading.get("score") == 1.0 and grading.get("max_score") == 1.0,
        "fail_closed_breakdown": breakdown.get("desktop_baseline_valid") == 1.0,
        "transcript_present": bool(transcript),
        "observed_desktop": bool(observations),
        "inspected_screenshot": _inspected_before_action(observations, image_reads, gui_actions),
        "used_gui_action": bool(gui_actions),
        "no_obvious_bypass": not bypassed,
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
