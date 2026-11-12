#!/usr/bin/env python3
"""Compare repeated desktop baseline runs and emit a compact evidence manifest."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

TASK_ID = "task_9000_desktop_notes_gui"
TARGET_TEXT = "AgentCanary desktop baseline complete"
STATE_FILENAME = "desktop_baseline_state.json"
MAX_STATE_BYTES = 64 * 1024


def _single_result(root: Path) -> dict[str, Any]:
    candidates = list(root.glob(f"job_*/task_{TASK_ID}/task_{TASK_ID}.json"))
    if len(candidates) != 1:
        raise ValueError(
            f"expected exactly one {TASK_ID} result under {root}, found {len(candidates)}"
        )
    data = json.loads(candidates[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("task_id") != TASK_ID:
        raise ValueError(f"invalid task result in {candidates[0]}")

    grading = data.get("grading")
    breakdown = grading.get("breakdown", {}) if isinstance(grading, dict) else {}
    if (
        not isinstance(grading, dict)
        or grading.get("score") != 1.0
        or grading.get("max_score") != 1.0
        or not isinstance(breakdown, dict)
        or breakdown.get("desktop_baseline_valid") != 1.0
    ):
        raise ValueError(f"run did not receive a full automated score: {grading!r}")

    workspace_value = data.get("workspace")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError("task result has no workspace path")
    workspace = Path(workspace_value)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError(f"task workspace is unavailable: {workspace}")

    state_path = workspace / STATE_FILENAME
    try:
        info = os.lstat(state_path)
    except OSError as exc:
        raise ValueError(f"cannot stat final state artifact {state_path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("final state artifact is not a single-link regular file")
    if info.st_size < 0 or info.st_size > MAX_STATE_BYTES:
        raise ValueError("final state artifact exceeds size limit")
    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes.decode("utf-8"))
    expected_state = {
        "current_text": TARGET_TEXT,
        "save_count": 1,
        "saved": True,
        "text": TARGET_TEXT,
    }
    if (
        not isinstance(state, dict)
        or type(state.get("save_count")) is not int
        or state != expected_state
    ):
        raise ValueError(f"unexpected final GUI state: {state!r}")

    transcript = data.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        raise ValueError("task transcript is missing")

    actions: list[str] = []
    action_positions: list[tuple[int, str]] = []
    observations: list[tuple[int, str]] = []
    reads: list[tuple[int, str]] = []
    image_hashes: list[str] = []
    sequence = 0

    for event in transcript:
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue

        if message.get("role") == "assistant":
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "toolCall":
                    continue
                name = item.get("name")
                args = item.get("arguments", {})
                if name == "exec" and isinstance(args, dict):
                    command = args.get("command")
                    if not isinstance(command, str):
                        sequence += 1
                        continue
                    if command.startswith("desktopctl observe "):
                        observations.append((sequence, command.split(maxsplit=2)[2]))
                    elif command.startswith(
                        ("desktopctl click ", "desktopctl type ", "desktopctl key ")
                    ):
                        actions.append(command)
                        action_positions.append((sequence, command))
                elif name == "read" and isinstance(args, dict):
                    path = args.get("path")
                    if isinstance(path, str):
                        reads.append((sequence, path))
                sequence += 1

        elif message.get("role") == "toolResult":
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "image":
                    continue
                if item.get("mimeType") != "image/png" or not isinstance(item.get("data"), str):
                    raise ValueError("screenshot tool result is not a PNG image payload")
                try:
                    raw = base64.b64decode(item["data"], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("screenshot image payload is not valid base64") from exc
                if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("screenshot image payload is not a PNG")
                image_hashes.append(hashlib.sha256(raw).hexdigest())

    if not actions or len(observations) < 2 or len(reads) < 2:
        raise ValueError("trajectory lacks the expected desktop observation/read/action loop")
    observed_paths = {path for _, path in observations}
    if any(path not in observed_paths for _, path in reads):
        raise ValueError("a screenshot read is not associated with a desktop observation")
    if len(image_hashes) != len(reads):
        raise ValueError(
            f"expected one image payload per screenshot read, got {len(image_hashes)} "
            f"for {len(reads)} reads"
        )

    action_bytes = json.dumps(
        actions, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    type_sequences = [
        sequence
        for sequence, command in action_positions
        if command.startswith("desktopctl type ")
    ]
    post_edit_observation_count = 0
    if type_sequences:
        last_type = max(type_sequences)
        save_sequences = [
            sequence
            for sequence, command in action_positions
            if sequence > last_type and command.startswith("desktopctl click ")
        ]
        if save_sequences:
            save_sequence = min(save_sequences)
            post_edit_observation_count = sum(
                1
                for sequence, _ in observations
                if last_type < sequence < save_sequence
            )

    return {
        "task_id": TASK_ID,
        "score": grading["score"],
        "model": data.get("model"),
        "job_id": data.get("job_id"),
        "execution_time_seconds": data.get("execution_time"),
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "gui_action_sha256": hashlib.sha256(action_bytes).hexdigest(),
        "gui_action_count": len(actions),
        "gui_actions": actions,
        "observation_count": len(observations),
        "screenshot_read_count": len(reads),
        "post_edit_observation_count": post_edit_observation_count,
        "verification_retry_count": max(0, post_edit_observation_count - 1),
        "screenshot_sha256": image_hashes,
    }


def compare_runs(
    first_root: Path,
    repeat_root: Path,
    *,
    mode: str,
    upstream_sha: str,
) -> dict[str, Any]:
    first = _single_result(first_root)
    repeat = _single_result(repeat_root)
    for key in ("state_sha256", "gui_action_sha256", "screenshot_sha256"):
        if first[key] != repeat[key]:
            raise ValueError(
                f"repeated {mode} runs differ in {key}: "
                f"{first[key]!r} != {repeat[key]!r}"
            )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "mode": mode,
        "upstream_master_sha": upstream_sha,
        "reproducible": {
            "final_state_bytes": True,
            "gui_action_sequence": True,
            "screenshots": True,
        },
        "runs": {"first": first, "repeat": repeat},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--repeat", required=True, type=Path)
    parser.add_argument(
        "--mode", required=True, choices=("reference", "openclaw-local-stub")
    )
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        manifest = compare_runs(
            args.first,
            args.repeat,
            mode=args.mode,
            upstream_sha=args.upstream_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"desktop reproducibility comparison failed: {exc}", file=sys.stderr)
        return 1

    first = manifest["runs"]["first"]
    print(
        json.dumps(
            {
                "mode": manifest["mode"],
                "upstream_master_sha": args.upstream_sha,
                "state_sha256": first["state_sha256"],
                "gui_action_sha256": first["gui_action_sha256"],
                "screenshot_sha256": first["screenshot_sha256"],
                "manifest": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
