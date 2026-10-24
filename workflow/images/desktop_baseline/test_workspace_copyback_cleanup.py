#!/usr/bin/env python3
"""Regression tests for cleanup when desktop workspace preservation fails."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
