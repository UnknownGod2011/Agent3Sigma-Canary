#!/usr/bin/env python3
"""Unit tests for repeated desktop-run evidence and manifest generation."""
from __future__ import annotations

import base64
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from compare_repeated_runs import compare_runs

TASK_ID = "task_9000_desktop_notes_gui"
TARGET = "AgentCanary desktop baseline complete"


def _png(marker: int = 0) -> bytes:
    # Full PNG decoding is already checked by verify_benchmark.py.
    return b"\x89PNG\r\n\x1a\n" + bytes([marker]) * 16


def _call(call_id: str, name: str, args: dict) -> dict:
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "toolCall", "id": call_id, "name": name, "arguments": args}
            ],
        },
    }


def _result(call_id: str, image: bytes | None = None) -> dict:
    content = []
    if image is not None:
        content.append(
            {
                "type": "image",
                "mimeType": "image/png",
                "data": base64.b64encode(image).decode("ascii"),
            }
        )
    else:
        content.append({"type": "text", "text": "ok"})
    return {
        "type": "message",
        "message": {"role": "toolResult", "toolCallId": call_id, "content": content},
    }


def _transcript(*, save_x: int = 359, image_marker: int = 0) -> list[dict]:
    calls = [
        ("c0", "exec", {"command": "desktopctl observe /tmp/before.png"}, None),
        ("c1", "read", {"path": "/tmp/before.png"}, _png(image_marker)),
        ("c2", "exec", {"command": "desktopctl click 124 152"}, None),
        ("c3", "exec", {"command": "desktopctl key Home"}, None),
        ("c4", "exec", {"command": "desktopctl key shift+End"}, None),
        ("c5", "exec", {"command": f"desktopctl type {TARGET}"}, None),
        ("c6", "exec", {"command": "desktopctl observe /tmp/after.png"}, None),
        ("c7", "read", {"path": "/tmp/after.png"}, _png(image_marker + 1)),
        ("c8", "exec", {"command": f"desktopctl click {save_x} 334"}, None),
    ]
    events = []
    for call_id, name, args, image in calls:
        events.append(_call(call_id, name, args))
        events.append(_result(call_id, image))
    return events


def _write_run(root: Path, *, save_x: int = 359, image_marker: int = 0) -> None:
    shutil.rmtree(root / "workspace", ignore_errors=True)
    shutil.rmtree(root / "job_test", ignore_errors=True)
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    state = {"current_text": TARGET, "save_count": 1, "saved": True, "text": TARGET}
    (workspace / "desktop_baseline_state.json").write_text(
        json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
    )

    job = root / "job_test" / f"task_{TASK_ID}"
    job.mkdir(parents=True)
    data = {
        "task_id": TASK_ID,
        "workspace": str(workspace),
        "grading": {
            "score": 1.0,
            "max_score": 1.0,
            "breakdown": {"desktop_baseline_valid": 1.0},
        },
        "transcript": _transcript(save_x=save_x, image_marker=image_marker),
        "model": "reference/desktop",
        "job_id": "job-test",
        "execution_time": 1.23,
    }
    (job / f"task_{TASK_ID}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


class CompareRepeatedRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.first = self.root / "first"
        self.repeat = self.root / "repeat"
        self.first.mkdir()
        self.repeat.mkdir()
        _write_run(self.first)
        _write_run(self.repeat)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_identical_runs_produce_reproducible_manifest(self) -> None:
        manifest = compare_runs(
            self.first, self.repeat, mode="reference", upstream_sha="abc123"
        )
        self.assertEqual(manifest["upstream_master_sha"], "abc123")
        self.assertTrue(manifest["reproducible"]["final_state_bytes"])
        self.assertTrue(manifest["reproducible"]["gui_action_sequence"])
        self.assertTrue(manifest["reproducible"]["screenshots"])
        first = manifest["runs"]["first"]
        self.assertEqual(first["gui_action_count"], 5)
        self.assertEqual(first["observation_count"], 2)
        self.assertEqual(first["screenshot_read_count"], 2)
        self.assertEqual(first["post_edit_observation_count"], 1)
        self.assertEqual(first["verification_retry_count"], 0)

    def test_action_mismatch_fails(self) -> None:
        _write_run(self.repeat, save_x=360)
        with self.assertRaisesRegex(ValueError, "gui_action_sha256"):
            compare_runs(
                self.first, self.repeat, mode="reference", upstream_sha="abc123"
            )

    def test_screenshot_mismatch_fails(self) -> None:
        _write_run(self.repeat, image_marker=1)
        with self.assertRaisesRegex(ValueError, "screenshot_sha256"):
            compare_runs(
                self.first, self.repeat, mode="reference", upstream_sha="abc123"
            )

    def test_invalid_final_state_fails(self) -> None:
        state_path = self.repeat / "workspace" / "desktop_baseline_state.json"
        state_path.write_text('{"saved":false}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected final GUI state"):
            compare_runs(
                self.first, self.repeat, mode="reference", upstream_sha="abc123"
            )

    def test_invalid_save_count_fails(self) -> None:
        state_path = self.repeat / "workspace" / "desktop_baseline_state.json"
        for invalid_count in (2, True, None):
            with self.subTest(save_count=invalid_count):
                state = {
                    "current_text": TARGET,
                    "save_count": invalid_count,
                    "saved": True,
                    "text": TARGET,
                }
                state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unexpected final GUI state"):
                    compare_runs(
                        self.first, self.repeat, mode="reference", upstream_sha="abc123"
                    )

    def test_incomplete_grade_fails(self) -> None:
        result = next(
            self.repeat.glob(f"job_*/task_{TASK_ID}/task_{TASK_ID}.json")
        )
        data = json.loads(result.read_text(encoding="utf-8"))
        data["grading"]["score"] = 0.0
        result.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "full automated score"):
            compare_runs(
                self.first, self.repeat, mode="reference", upstream_sha="abc123"
            )


if __name__ == "__main__":
    unittest.main()
