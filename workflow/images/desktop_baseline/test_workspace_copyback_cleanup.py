#!/usr/bin/env python3
"""Regression tests for desktop state-artifact copyback and container cleanup."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_reference_benchmark as runner  # noqa: E402


class WorkspaceCopybackCleanupTests(unittest.TestCase):
    def test_container_stop_runs_even_if_copyback_raises(self) -> None:
        with (
            patch.object(runner.docker, "is_active", return_value=True),
            patch.object(
                runner,
                "_copy_task_workspaces_to_host",
                side_effect=RuntimeError("copyback failed"),
            ),
            patch.object(runner, "_original_stop") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "copyback failed"):
                runner._stop_with_workspace_copyback()
            stop.assert_called_once_with()

    def test_copyback_precedes_normal_stop(self) -> None:
        events: list[str] = []
        with (
            patch.object(runner.docker, "is_active", return_value=True),
            patch.object(
                runner,
                "_copy_task_workspaces_to_host",
                side_effect=lambda: events.append("copyback"),
            ),
            patch.object(
                runner,
                "_original_stop",
                side_effect=lambda: events.append("stop"),
            ),
        ):
            runner._stop_with_workspace_copyback()
        self.assertEqual(events, ["copyback", "stop"])

    def test_authoritative_container_state_replaces_workspace_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            state_path = workspace / runner.STATE_ARTIFACT_NAME
            state_path.write_text('{"saved": false, "text": "agent-supplied"}', encoding="utf-8")
            events: list[list[str]] = []

            def fake_run(args, **kwargs):
                events.append(args)
                if args[:3] == ["docker", "exec", "container-id"]:
                    self.assertEqual(args[3:5], ["sh", "-c"])
                    self.assertIn(runner.STATE_ARTIFACT_IN_CONTAINER, args[5])
                    return SimpleNamespace(returncode=0, stdout="present\n", stderr="")
                if args[:2] == ["docker", "cp"]:
                    self.assertEqual(args[2], f"container-id:{runner.STATE_ARTIFACT_IN_CONTAINER}")
                    destination = Path(args[3])
                    destination.write_text(
                        json.dumps({
                            "saved": True,
                            "text": "AgentCanary desktop baseline complete",
                            "current_text": "AgentCanary desktop baseline complete",
                        }),
                        encoding="utf-8",
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                raise AssertionError(f"unexpected subprocess call: {args!r}")

            with patch.object(runner.subprocess, "run", side_effect=fake_run):
                copied = runner._copy_grader_state_artifact_to_host("container-id", workspace)

            self.assertTrue(copied)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1][:2], ["docker", "cp"])
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                {
                    "saved": True,
                    "text": "AgentCanary desktop baseline complete",
                    "current_text": "AgentCanary desktop baseline complete",
                },
            )
            self.assertFalse((workspace / ".desktop_baseline_state.json.copyback").exists())

    def test_missing_container_state_removes_untrusted_workspace_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            state_path = workspace / runner.STATE_ARTIFACT_NAME
            state_path.mkdir()
            (state_path / "fake.json").write_text('{"saved": true}', encoding="utf-8")

            def fake_run(args, **kwargs):
                self.assertEqual(args[:3], ["docker", "exec", "container-id"])
                self.assertIn(runner.STATE_ARTIFACT_IN_CONTAINER, args[5])
                return SimpleNamespace(returncode=0, stdout="missing\n", stderr="")

            with patch.object(runner.subprocess, "run", side_effect=fake_run):
                copied = runner._copy_grader_state_artifact_to_host("container-id", workspace)

            self.assertFalse(copied)
            self.assertFalse(state_path.exists())
            self.assertFalse((workspace / ".desktop_baseline_state.json.copyback").exists())


    def test_multiple_workspace_candidates_fail_closed_before_copyback(self) -> None:
        events: list[list[str]] = []

        def fake_run(args, **kwargs):
            events.append(args)
            self.assertEqual(args[:3], ["docker", "exec", "container-id"])
            self.assertIn("find", args)
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "/tmp/scry/task-1/agent_workspace"
                    + chr(10)
                    + "/tmp/scry/agent-created/agent_workspace"
                    + chr(10)
                ),
                stderr="",
            )

        with (
            patch.object(runner.docker, "get_container_id", return_value="container-id"),
            patch.object(runner.subprocess, "run", side_effect=fake_run),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "expected exactly one Docker task agent_workspace before grading, found 2",
            ):
                runner._copy_task_workspaces_to_host()

        # Fail closed before any docker cp can move agent-controlled workspace
        # contents into the host's grading area.
        self.assertEqual(len(events), 1)
        self.assertNotIn("cp", events[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
