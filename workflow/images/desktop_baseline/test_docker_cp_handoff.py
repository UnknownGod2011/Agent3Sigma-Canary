from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import docker_cp_handoff as handoff
import run_docker_cp_benchmark as runner

CONTAINER_ID = "a" * 64
PAYLOAD = b'{"current_text":"AgentCanary desktop baseline complete","save_count":1,"saved":true,"text":"AgentCanary desktop baseline complete"}'


class DockerCpHandoffTests(unittest.TestCase):
    def test_copies_only_the_fixed_container_path_and_returns_validated_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_run(args, **kwargs):
                calls.append((args, kwargs))
                Path(args[-1]).write_bytes(PAYLOAD)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(handoff.subprocess, "run", side_effect=fake_run):
                actual = handoff.copy_container_artifact(CONTAINER_ID, tmp)

            self.assertEqual(actual, PAYLOAD)
            self.assertEqual(
                calls[0][0],
                [
                    "docker",
                    "cp",
                    f"{CONTAINER_ID}:{handoff.CONTAINER_STATE_PATH}",
                    str(Path(tmp) / handoff.STATE_ARTIFACT_NAME),
                ],
            )
            self.assertFalse(calls[0][1]["check"])
            self.assertEqual(calls[0][1]["timeout"], 15)

    def test_rejects_invalid_container_id_before_docker_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(handoff.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "container id"):
                    handoff.copy_container_artifact("not-a-container", tmp)
                run.assert_not_called()

    def test_rejects_symlink_staging_directory_before_docker_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with patch.object(handoff.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "real directory"):
                    handoff.copy_container_artifact(CONTAINER_ID, link)
                run.assert_not_called()

    def test_rejects_preexisting_destination_before_docker_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / handoff.STATE_ARTIFACT_NAME).write_bytes(PAYLOAD)
            with patch.object(handoff.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "must not already exist"):
                    handoff.copy_container_artifact(CONTAINER_ID, tmp)
                run.assert_not_called()

    def test_fails_closed_on_docker_cp_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = SimpleNamespace(returncode=1, stdout="", stderr="No such file")
            with patch.object(handoff.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "docker cp failed"):
                    handoff.copy_container_artifact(CONTAINER_ID, tmp)

    def test_fails_closed_on_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = subprocess.TimeoutExpired(["docker", "cp"], 15)
            with patch.object(handoff.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    handoff.copy_container_artifact(CONTAINER_ID, tmp)

    def test_rejects_symlink_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp).parent / f"{Path(tmp).name}-outside.json"
            outside.write_bytes(PAYLOAD)

            def fake_run(args, **kwargs):
                Path(args[-1]).symlink_to(outside)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            try:
                with patch.object(handoff.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(RuntimeError, "symlink"):
                        handoff.copy_container_artifact(CONTAINER_ID, tmp)
            finally:
                outside.unlink(missing_ok=True)

    def test_rejects_hardlinked_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp).parent / f"{Path(tmp).name}-outside.json"
            outside.write_bytes(PAYLOAD)

            def fake_run(args, **kwargs):
                os.link(outside, Path(args[-1]))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            try:
                with patch.object(handoff.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(RuntimeError, "single-link regular file"):
                        handoff.copy_container_artifact(CONTAINER_ID, tmp)
            finally:
                outside.unlink(missing_ok=True)

    def test_rejects_oversized_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(args, **kwargs):
                Path(args[-1]).write_bytes(b"x" * (64 * 1024 + 1))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(handoff.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "size limit"):
                    handoff.copy_container_artifact(CONTAINER_ID, tmp)

    def test_benchmark_stop_exports_artifact_before_removing_container(self):
        baseline = runner.baseline
        old_workspace = baseline._task_workspace_for_copyback
        old_exporter = baseline._copy_grader_state_artifact_to_host
        old_stop = baseline._original_stop
        workspace = Path("/tmp/scry") / uuid.uuid4().hex / "agent_workspace"
        events = []

        def fake_copy(container_id, staging_dir):
            events.append("docker-cp")
            return PAYLOAD

        def fake_write(root, data, filename):
            events.append("host-write")
            Path(root).mkdir(parents=True, exist_ok=True)
            (Path(root) / filename).write_bytes(data)
            return True

        try:
            baseline._task_workspace_for_copyback = workspace
            runner.install_docker_cp_exporter()
            with (
                patch.object(baseline.docker, "is_active", return_value=True),
                patch.object(baseline.docker, "get_container_id", return_value=CONTAINER_ID),
                patch.object(baseline, "_original_stop", side_effect=lambda: events.append("container-remove")),
                patch.object(runner, "copy_container_artifact", side_effect=fake_copy),
                patch.object(baseline.safe_export, "write_state_artifact", side_effect=fake_write),
            ):
                baseline._stop_with_artifact_export()

            self.assertEqual(events, ["docker-cp", "host-write", "container-remove"])
            self.assertEqual((workspace / baseline.STATE_ARTIFACT_NAME).read_bytes(), PAYLOAD)
        finally:
            baseline._task_workspace_for_copyback = old_workspace
            baseline._copy_grader_state_artifact_to_host = old_exporter
            baseline._original_stop = old_stop
            import shutil
            shutil.rmtree(workspace.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
