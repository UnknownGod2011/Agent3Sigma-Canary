#!/usr/bin/env python3
"""Unit tests for cross-adapter desktop artifact-handoff equivalence."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from compare_handoff_modes import compare_handoff_modes


class CompareHandoffModesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.first = self.root / "bind-mount.json"
        self.second = self.root / "docker-cp.json"
        self.manifest = self._manifest()
        self._write(self.first, self.manifest)
        self._write(self.second, self.manifest)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _manifest() -> dict:
        run = {
            "state_sha256": "a" * 64,
            "gui_action_sha256": "b" * 64,
            "gui_actions": ["desktopctl click 1 2", "desktopctl click 3 4"],
            "screenshot_sha256": ["c" * 64, "d" * 64],
            "score": 1.0,
            "gui_action_count": 2,
            "observation_count": 2,
            "screenshot_read_count": 2,
            "post_edit_observation_count": 1,
            "verification_retry_count": 0,
        }
        return {
            "schema_version": 2,
            "task_id": "task_9000_desktop_notes_gui",
            "mode": "reference",
            "upstream_master_sha": "e" * 40,
            "task_definition_sha256": "f" * 64,
            "reproducible": {
                "final_state_bytes": True,
                "gui_action_sequence": True,
                "screenshots": True,
            },
            "runs": {"first": copy.deepcopy(run), "repeat": copy.deepcopy(run)},
        }

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def _mutate_second(self, callback) -> None:
        changed = copy.deepcopy(self.manifest)
        callback(changed)
        self._write(self.second, changed)

    @staticmethod
    def _set_both_runs(manifest: dict, key: str, value) -> None:
        for run_name in ("first", "repeat"):
            manifest["runs"][run_name][key] = copy.deepcopy(value)

    def test_equivalent_handoff_modes_pass(self) -> None:
        result = compare_handoff_modes(self.first, self.second)
        self.assertTrue(result["equivalent"])
        self.assertEqual(result["runs_compared"], ["first", "repeat"])
        self.assertEqual(result["task_definition_sha256"], "f" * 64)

    def test_task_definition_mismatch_fails(self) -> None:
        self._mutate_second(lambda m: m.update(task_definition_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "differ in task_definition_sha256"):
            compare_handoff_modes(self.first, self.second)

    def test_invalid_task_definition_hash_fails(self) -> None:
        self._mutate_second(lambda m: m.update(task_definition_sha256="not-a-sha256"))
        with self.assertRaisesRegex(ValueError, "invalid task_definition_sha256"):
            compare_handoff_modes(self.first, self.second)

    def test_state_artifact_mismatch_fails(self) -> None:
        self._mutate_second(
            lambda m: self._set_both_runs(m, "state_sha256", "f" * 64)
        )
        with self.assertRaisesRegex(ValueError, "runs.first.state_sha256"):
            compare_handoff_modes(self.first, self.second)

    def test_gui_action_mismatch_fails(self) -> None:
        self._mutate_second(
            lambda m: self._set_both_runs(m, "gui_action_sha256", "f" * 64)
        )
        with self.assertRaisesRegex(ValueError, "runs.first.gui_action_sha256"):
            compare_handoff_modes(self.first, self.second)

    def test_screenshot_mismatch_fails(self) -> None:
        self._mutate_second(
            lambda m: [
                m["runs"][name].update(
                    screenshot_sha256=["f" * 64], screenshot_read_count=1
                )
                for name in ("first", "repeat")
            ]
        )
        with self.assertRaisesRegex(ValueError, "runs.first.screenshot_sha256"):
            compare_handoff_modes(self.first, self.second)

    def test_agent_mode_mismatch_fails(self) -> None:
        self._mutate_second(lambda m: m.update(mode="openclaw-local-stub"))
        with self.assertRaisesRegex(ValueError, "differ in mode"):
            compare_handoff_modes(self.first, self.second)

    def test_upstream_revision_mismatch_fails(self) -> None:
        self._mutate_second(lambda m: m.update(upstream_master_sha="f" * 40))
        with self.assertRaisesRegex(ValueError, "differ in upstream_master_sha"):
            compare_handoff_modes(self.first, self.second)

    def test_unreproducible_manifest_fails(self) -> None:
        self._mutate_second(lambda m: m["reproducible"].update(screenshots=False))
        with self.assertRaisesRegex(ValueError, "not internally reproducible"):
            compare_handoff_modes(self.first, self.second)

    def test_non_full_score_fails(self) -> None:
        self._mutate_second(lambda m: m["runs"]["first"].update(score=0.0))
        with self.assertRaisesRegex(ValueError, "full automated score"):
            compare_handoff_modes(self.first, self.second)

    def test_cross_mode_metric_mismatch_fails(self) -> None:
        self._mutate_second(
            lambda m: self._set_both_runs(m, "observation_count", 3)
        )
        with self.assertRaisesRegex(ValueError, "runs.first.observation_count"):
            compare_handoff_modes(self.first, self.second)

    def test_repeatability_claim_is_revalidated(self) -> None:
        self._mutate_second(
            lambda m: m["runs"]["repeat"].update(
                gui_actions=["different"], gui_action_count=1
            )
        )
        with self.assertRaisesRegex(ValueError, "not repeatable in gui_actions"):
            compare_handoff_modes(self.first, self.second)

    def test_repeat_metrics_must_match(self) -> None:
        self._mutate_second(lambda m: m["runs"]["repeat"].update(observation_count=3))
        with self.assertRaisesRegex(ValueError, "not repeatable in observation_count"):
            compare_handoff_modes(self.first, self.second)


if __name__ == "__main__":
    unittest.main()
