#!/usr/bin/env python3
"""Regression tests for opt-in fail-closed run_command pre-setup."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lib_agent  # noqa: E402


class RequiredRunCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path("/tmp/scry/" + "a" * 32 + "/agent_workspace")

    def test_default_nonzero_exit_remains_best_effort_in_docker(self) -> None:
        result = subprocess.CompletedProcess(["sh", "-c", "false"], 7, "", "setup failed")
        with patch.object(lib_agent.docker, "is_active", return_value=True), patch.object(
            lib_agent.docker, "run_cmd", return_value=result
        ):
            self.assertIsNone(
                lib_agent._execute_run_command_setup(
                    {"command": "false"}, self.workspace, "task_optional_setup"
                )
            )

    def test_required_nonzero_exit_fails_in_docker(self) -> None:
        result = subprocess.CompletedProcess(["sh", "-c", "false"], 7, "", "setup failed")
        with patch.object(lib_agent.docker, "is_active", return_value=True), patch.object(
            lib_agent.docker, "run_cmd", return_value=result
        ):
            with self.assertRaisesRegex(RuntimeError, "required pre_setup command failed: exited with status 7"):
                lib_agent._execute_run_command_setup(
                    {"command": "false", "required": True},
                    self.workspace,
                    "task_required_setup",
                )

    def test_required_timeout_fails_in_docker(self) -> None:
        timeout = subprocess.TimeoutExpired(["sh", "-c", "sleep 2"], 1)
        with patch.object(lib_agent.docker, "is_active", return_value=True), patch.object(
            lib_agent.docker, "run_cmd", side_effect=timeout
        ):
            with self.assertRaisesRegex(RuntimeError, "required pre_setup command failed: timed out after 1s"):
                lib_agent._execute_run_command_setup(
                    {"command": "sleep 2", "timeout": 1, "required": True},
                    self.workspace,
                    "task_required_timeout",
                )

    def test_required_nonzero_exit_fails_in_local_mode(self) -> None:
        result = subprocess.CompletedProcess(["false"], 3, "", "setup failed")
        with patch.object(lib_agent.docker, "is_active", return_value=False), patch.object(
            lib_agent.subprocess, "run", return_value=result
        ):
            with self.assertRaisesRegex(RuntimeError, r"required pre_setup command failed: exited with status 3 \(local\)"):
                lib_agent._execute_run_command_setup(
                    {"command": ["false"], "required": True},
                    self.workspace,
                    "task_required_local_setup",
                )

    def test_required_missing_command_fails_before_execution(self) -> None:
        with patch.object(lib_agent.docker, "is_active", return_value=True), patch.object(
            lib_agent.docker, "run_cmd"
        ) as run_cmd:
            with self.assertRaisesRegex(RuntimeError, "required pre_setup command failed: missing or invalid command"):
                lib_agent._execute_run_command_setup(
                    {"required": True}, self.workspace, "task_missing_setup"
                )
            run_cmd.assert_not_called()


    def test_required_setup_failure_aborts_before_agent_invocation(self) -> None:
        from types import SimpleNamespace

        task = SimpleNamespace(
            task_id="task_required_setup",
            name="Required setup task",
            category="desktop_baseline",
            timeout_seconds=120,
            prompt="Perform the task.",
            frontmatter={
                "pre_setup": [
                    {
                        "type": "run_command",
                        "required": True,
                        "command": "desktopctl start",
                    }
                ]
            },
        )
        workspace = Path("/tmp/scry/" + "b" * 32 + "/agent_workspace")

        with (
            patch.object(lib_agent, "cleanup_agent_sessions"),
            patch.object(lib_agent, "prepare_task_workspace"),
            patch.object(lib_agent.docker, "is_active", return_value=True),
            patch.object(lib_agent.docker, "copy_to_container"),
            patch.object(
                lib_agent,
                "_run_deferred_pre_setup_commands",
                side_effect=RuntimeError(
                    "run_command: task task_required_setup required pre_setup command failed"
                ),
            ),
            patch.object(lib_agent, "run_openclaw_prompt") as run_prompt,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "required pre_setup command failed"
            ):
                lib_agent.execute_openclaw_task(
                    task=task,
                    agent_id="required-setup-test",
                    model_id="test/model",
                    run_id="required-setup-run",
                    timeout_multiplier=1.0,
                    skill_dir=Path("/tmp/skills"),
                    task_agent_workspace_root=Path("/tmp/scry"),
                    task_agent_workspace_root_relate=workspace,
                    local_task_agent_workspace_root_relate=workspace,
                )

            run_prompt.assert_not_called()



if __name__ == "__main__":
    unittest.main()
