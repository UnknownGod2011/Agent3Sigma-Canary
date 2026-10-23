#!/usr/bin/env python3
"""Fail-closed verifier for the real desktop-baseline benchmark artifact.

The verifier checks the saved AgentCanary result and independently re-runs the
task's deterministic grade against the recorded transcript and copied-back
workspace. A claimed score is not accepted unless the same task grader can
reproduce it from the artifact's evidence.
"""
from __future__ import annotations

import json
import posixpath
import re
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib_grading import grade_task  # noqa: E402
from lib_tasks import TaskLoader  # noqa: E402

TASK_ID = "task_9000_desktop_notes_gui"
TASK_PATH = REPO_ROOT / "tasks" / "desktop_baseline" / f"{TASK_ID}.md"
DEFAULT_SCREENSHOT = "/tmp/agentcanary-desktop/screen.png"
FORBIDDEN = (
    "desktop_baseline_state.json",
    "notes_app.py",
    "/opt/agentcanary-desktop",
)


def _command_segments(command: str) -> list[list[str]]:
    # Split only at top-level shell separators; quoted text remains one arg.
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
                    return []
                if not tokens:
                    return []
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
            return []
        if not tokens:
            return []
        segments.append(tokens)
    return segments


def _observed_path(command: str) -> str | None:
    for tokens in _command_segments(command):
        if len(tokens) >= 2 and tokens[0] == "desktopctl" and tokens[1] == "observe":
            if len(tokens) == 2:
                return DEFAULT_SCREENSHOT
            if (
                len(tokens) == 3
                and re.fullmatch(r"/tmp/[A-Za-z0-9._/-]+\.png", tokens[2])
                and ".." not in tokens[2].split("/")
            ):
                return posixpath.normpath(tokens[2])
    return None


def _tool_results(transcript: list) -> dict[str, list[tuple[int, dict]]]:
    results: dict[str, list[tuple[int, dict]]] = {}
    for event_index, event in enumerate(transcript):
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        call_id = message.get("toolCallId")
        if isinstance(call_id, str) and call_id:
            results.setdefault(call_id, []).append((event_index, message))
    return results


def _successful_result(
    results: dict[str, list[tuple[int, dict]]],
    call_id: str,
    call_event_index: int,
    *,
    require_content: bool = False,
) -> bool:
    if not isinstance(call_id, str) or not call_id:
        return False
    matches = results.get(call_id, [])
    if len(matches) != 1:
        return False
    result_event_index, result_message = matches[0]
    if result_event_index <= call_event_index or result_message.get("isError") is not False:
        return False
    return not require_content or bool(result_message.get("content"))


def _evidence(
    transcript: list,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[tuple[int, str]], bool]:
    observations: list[tuple[int, str]] = []
    image_reads: list[tuple[int, str]] = []
    gui_actions: list[tuple[int, str]] = []
    results = _tool_results(transcript)
    seen_call_ids = set()
    invalid_or_bypassed = False
    sequence = 0

    for event_index, event in enumerate(transcript):
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
            call_sequence = sequence
            sequence += 1
            call_id = item.get("id")
            if not isinstance(call_id, str) or not call_id or call_id in seen_call_ids:
                invalid_or_bypassed = True
            else:
                seen_call_ids.add(call_id)

            args = item.get("arguments", {})
            if not isinstance(args, dict):
                invalid_or_bypassed = True
                continue
            args_text = json.dumps(args, ensure_ascii=False).lower()
            if any(marker in args_text for marker in FORBIDDEN):
                invalid_or_bypassed = True

            name = item.get("name")
            if name == "exec":
                command = args.get("command")
                if (
                    not isinstance(command, str)
                    or not _successful_result(results, call_id, event_index)
                ):
                    invalid_or_bypassed = True
                    continue
                segments = _command_segments(command)
                if not segments or any(
                    len(tokens) < 2
                    or tokens[0] != "desktopctl"
                    or tokens[1] not in {"observe", "click", "type", "key"}
                    for tokens in segments
                ):
                    invalid_or_bypassed = True
                path = _observed_path(command)
                if path is not None:
                    observations.append((call_sequence, path))
                if any(
                    len(tokens) >= 2 and tokens[0] == "desktopctl"
                    and tokens[1] in {"click", "type", "key"}
                    for tokens in segments
                ):
                    gui_actions.append((call_sequence, command))
            elif name == "read":
                path = args.get("path")
                if (
                    set(args) != {"path"}
                    or not isinstance(path, str)
                    or not re.fullmatch(r"/tmp/[A-Za-z0-9._/-]+\.png", posixpath.normpath(path))
                    or ".." in path.split("/")
                    or not _successful_result(results, call_id, event_index, require_content=True)
                ):
                    invalid_or_bypassed = True
                    continue
                image_reads.append((call_sequence, posixpath.normpath(path)))
            else:
                # Tool-looking text in another tool's arguments is not GUI evidence.
                invalid_or_bypassed = True

    if any(call_id not in seen_call_ids for call_id in results):
        invalid_or_bypassed = True
    observed_paths = {path for _, path in observations}
    if any(path not in observed_paths for _, path in image_reads):
        invalid_or_bypassed = True
    return observations, image_reads, gui_actions, invalid_or_bypassed


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


def _recompute_grade(workspace_path: str, transcript: list) -> bool:
    try:
        task = TaskLoader(REPO_ROOT / "tasks").load_task(TASK_PATH)
        result = grade_task(
            task=task,
            execution_result={"workspace": workspace_path, "transcript": transcript},
            skill_dir=REPO_ROOT / "skills",
        )
    except Exception as exc:
        print(f"warning: could not recompute desktop task grade: {exc}", file=sys.stderr)
        return False
    return (
        result.score == 1.0
        and result.breakdown.get("desktop_baseline_valid") == 1.0
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
    workspace_path = data.get("workspace")
    if not isinstance(workspace_path, str):
        workspace_path = ""

    observations, image_reads, gui_actions, bypassed = _evidence(transcript)
    checks = {
        "task_id": data.get("task_id") == TASK_ID,
        "full_grade": grading.get("score") == 1.0 and grading.get("max_score") == 1.0,
        "fail_closed_breakdown": breakdown.get("desktop_baseline_valid") == 1.0,
        "recomputed_grade": _recompute_grade(workspace_path, transcript),
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
