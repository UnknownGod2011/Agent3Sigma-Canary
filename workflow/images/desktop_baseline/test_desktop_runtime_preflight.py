#!/usr/bin/env python3
"""Regression tests for the desktop runner's fail-fast X11 readiness gate."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workflow.images.desktop_baseline import run_reference_benchmark as runner  # noqa: E402


class DesktopRuntimePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path("/tmp/scry/" + "a" * 32 + "/agent_workspace")
        self.task = SimpleNamespace(
            task_id=runner.DESKTOP_TASK_ID,
            file_path=Path("tasks/desktop_baseline/task_9000_desktop_notes_gui.md"),
        )

    def _setup_patch(self, events: list[str]):
        def setup(task, workspace):
            events.append("setup")
        return patch.object(
            runner,
            "_original_run_deferred_pre_setup_commands",
            side_effect=setup,
        )

    def test_checks_display_and_visible_window_after_setup(self) -> None:
        events: list[str] = []

        def run_cmd(args, **kwargs):
            events.append("preflight")
            self.assertEqual(args[:2], ["sh", "-c"])
            self.assertIn("xdpyinfo -display :99", args[2])
            self.assertIn("xdotool search --onlyvisible --name", args[2])
            self.assertEqual(kwargs["cwd"], str(self.workspace))
            self.assertEqual(kwargs["timeout"], 10)
            return subprocess.CompletedProcess(args, 0, "", "")

        with self._setup_patch(events), patch.object(
            runner.docker, "is_active", return_value=True
        ), patch.object(runner.docker, "run_cmd", side_effect=run_cmd):
            runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                self.task, self.workspace
            )

        self.assertEqual(events, ["setup", "preflight"])

    def test_missing_display_or_window_fails_closed(self) -> None:
        events: list[str] = []

        def run_cmd(args, **kwargs):
            events.append("preflight")
            return subprocess.CompletedProcess(args, 1, "", "unable to open display")

        with self._setup_patch(events), patch.object(
            runner.docker, "is_active", return_value=True
        ), patch.object(runner.docker, "run_cmd", side_effect=run_cmd):
            with self.assertRaisesRegex(RuntimeError, "unable to open display"):
                runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                    self.task, self.workspace
                )

        self.assertEqual(events, ["setup", "preflight"])

    def test_preflight_timeout_fails_closed(self) -> None:
        events: list[str] = []

        def run_cmd(args, **kwargs):
            events.append("preflight")
            raise subprocess.TimeoutExpired(args, timeout=10)

        with self._setup_patch(events), patch.object(
            runner.docker, "is_active", return_value=True
        ), patch.object(runner.docker, "run_cmd", side_effect=run_cmd):
            with self.assertRaisesRegex(RuntimeError, "timed out after 10 seconds"):
                runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                    self.task, self.workspace
                )

        self.assertEqual(events, ["setup", "preflight"])

    def test_swallowed_run_command_failure_is_caught_by_gui_preflight(self) -> None:
        # The current AgentCanary run_command setup contract deliberately
        # swallows non-zero exits. Confirm this task-specific GUI gate catches
        # the resulting missing display before the benchmark can invoke an agent.
        events: list[list[str]] = []
        task = SimpleNamespace(
            task_id=runner.DESKTOP_TASK_ID,
            file_path=Path("tasks/desktop_baseline/task_9000_desktop_notes_gui.md"),
            frontmatter={
                "pre_setup": [{"type": "run_command", "command": "false"}],
            },
        )

        def run_cmd(args, **kwargs):
            events.append(list(args))
            if len(events) == 1:
                self.assertEqual(args, ["sh", "-c", "false"])
                return subprocess.CompletedProcess(
                    args, 1, "", "simulated setup failure"
                )

            self.assertEqual(args[:2], ["sh", "-c"])
            self.assertIn("xdpyinfo -display :99", args[2])
            return subprocess.CompletedProcess(
                args, 1, "", "unable to open display"
            )

        with patch.object(
            runner.docker, "is_active", return_value=True
        ), patch.object(runner.docker, "run_cmd", side_effect=run_cmd):
            with self.assertRaisesRegex(RuntimeError, "GUI preflight failed"):
                runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                    task, self.workspace
                )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], ["sh", "-c", "false"])

    def test_preflight_requires_active_container(self) -> None:
        events: list[str] = []

        with self._setup_patch(events), patch.object(
            runner.docker, "is_active", return_value=False
        ), patch.object(runner.docker, "run_cmd") as run_cmd:
            with self.assertRaisesRegex(RuntimeError, "active Docker container"):
                runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                    self.task, self.workspace
                )
            run_cmd.assert_not_called()

        self.assertEqual(events, ["setup"])

    def test_other_task_does_not_probe_desktop(self) -> None:
        events: list[str] = []
        other_task = SimpleNamespace(task_id="task_unrelated")

        with self._setup_patch(events), patch.object(
            runner.docker, "run_cmd"
        ) as run_cmd:
            runner._run_deferred_pre_setup_commands_with_desktop_preflight(
                other_task, self.workspace
            )
            run_cmd.assert_not_called()

        self.assertEqual(events, ["setup"])


if __name__ == "__main__":
    unittest.main()
