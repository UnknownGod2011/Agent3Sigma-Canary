#!/usr/bin/env python3
"""Unit tests for the desktop bind-mount runner's teardown ordering."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_bind_mount_benchmark as runner


class BindMountRunnerTests(unittest.TestCase):
    def test_host_artifact_is_read_only_after_container_stop(self):
        baseline = runner.baseline
        active = {"value": False}
        events: list[str] = []
        workspace_root = Path(tempfile.mkdtemp(prefix="agentcanary-bindmount-test-"))
        workspace = workspace_root / "agent_workspace"
        payload = b'{"current_text":"ok","saved":true,"text":"ok"}'
        mounts_seen = []

        original_docker_start = baseline.docker.start
        original_docker_stop = baseline.docker.stop
        original_original_stop = baseline._original_stop
        original_workspace = baseline._task_workspace_for_copyback
        original_argv = sys.argv
        real_read = runner.read_host_artifact
        real_write = baseline.safe_export.write_state_artifact

        def fake_start(*, extra_mounts=None, **kwargs):
            mounts_seen.extend(extra_mounts or [])
            active["value"] = True
            events.append("start")
            return "container-id"

        def fake_stop():
            events.append("stop")
            active["value"] = False

        def fake_benchmark_main():
            baseline.docker.start(
                extra_mounts=[("/skills/demo", "/root/.openclaw/skills/demo", "ro")],
                defer_image_gateway=False,
            )
            assert runner._host_artifact_dir is not None
            (runner._host_artifact_dir / baseline.STATE_ARTIFACT_NAME).write_bytes(payload)
            baseline._task_workspace_for_copyback = workspace
            baseline.docker.stop()

        def read_after_stop(directory, filename):
            self.assertFalse(active["value"], "artifact was read before Docker teardown")
            events.append("read")
            return real_read(directory, filename)

        def write_workspace_artifact(root, data, filename):
            events.append("write")
            return real_write(root, data, filename)

        try:
            sys.argv = ["run_bind_mount_benchmark.py"]
            with (
                patch.object(runner, "_original_start", side_effect=fake_start),
                patch.object(baseline, "_original_stop", side_effect=fake_stop),
                patch.object(baseline.docker, "is_active", side_effect=lambda: active["value"]),
                patch.object(baseline.benchmark, "main", side_effect=fake_benchmark_main),
                patch.object(runner, "read_host_artifact", side_effect=read_after_stop),
                patch.object(baseline.safe_export, "write_state_artifact", side_effect=write_workspace_artifact),
            ):
                runner.main()

            self.assertEqual(events, ["start", "stop", "read", "write"])
            self.assertEqual(mounts_seen[0], ("/skills/demo", "/root/.openclaw/skills/demo", "ro"))
            self.assertEqual(mounts_seen[-1][1:], ("/tmp/agentcanary-desktop", "rw"))
            self.assertEqual((workspace / baseline.STATE_ARTIFACT_NAME).read_bytes(), payload)
        finally:
            baseline.docker.start = original_docker_start
            baseline.docker.stop = original_docker_stop
            baseline._original_stop = original_original_stop
            baseline._task_workspace_for_copyback = original_workspace
            sys.argv = original_argv
            shutil.rmtree(workspace_root, ignore_errors=True)

    def test_no_mount_mode_requires_the_verified_negative_control_flags(self):
        original_argv = sys.argv
        try:
            sys.argv = ["run_bind_mount_benchmark.py", "--no-artifact-mount"]
            with self.assertRaisesRegex(SystemExit, "reserved for the no-copyback negative control"):
                runner.main()
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    unittest.main(verbosity=2)
