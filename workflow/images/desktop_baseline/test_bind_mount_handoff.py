#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from bind_mount_handoff import (
    CONTAINER_ARTIFACT_DIR,
    MAX_STATE_BYTES,
    append_artifact_mount,
    read_host_artifact,
)


class BindMountHandoffTests(unittest.TestCase):
    def test_mount_is_appended_without_mutating_existing_skill_mounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = [("/skills/demo", "/root/.openclaw/skills/demo", "ro")]
            result = append_artifact_mount(existing, tmp)
            self.assertEqual(result[0], existing[0])
            self.assertEqual(result[1], (str(Path(tmp).resolve()), CONTAINER_ARTIFACT_DIR, "rw"))
            self.assertEqual(existing, [("/skills/demo", "/root/.openclaw/skills/demo", "ro")])

    def test_mount_rejects_duplicate_container_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "already in use"):
                append_artifact_mount([("/other", CONTAINER_ARTIFACT_DIR, "ro")], tmp)

    def test_mount_rejects_normalized_duplicate_container_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "already in use"):
                append_artifact_mount([("/other", CONTAINER_ARTIFACT_DIR + "/.", "ro")], tmp)

    def test_mount_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "real directory"):
                append_artifact_mount([], link)

    def test_reads_regular_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = b'{"saved":true}'
            (Path(tmp) / "desktop_baseline_state.json").write_bytes(expected)
            self.assertEqual(read_host_artifact(tmp), expected)

    def test_missing_artifact_is_reported_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_host_artifact(tmp))

    def test_refuses_symlink_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.json"
            outside.write_bytes(b'{"saved":true}')
            (root / "desktop_baseline_state.json").symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, "refusing unsafe mounted artifact"):
                read_host_artifact(root)

    def test_refuses_hardlinked_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_bytes(b'{"saved":true}')
            os.link(source, root / "desktop_baseline_state.json")
            with self.assertRaisesRegex(RuntimeError, "single-link regular file"):
                read_host_artifact(root)

    def test_refuses_oversized_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "desktop_baseline_state.json").write_bytes(b"x" * (MAX_STATE_BYTES + 1))
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                read_host_artifact(tmp)

    def test_refuses_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkfifo(Path(tmp) / "desktop_baseline_state.json")
            with self.assertRaisesRegex(RuntimeError, "single-link regular file"):
                read_host_artifact(tmp)

    def test_refuses_symlink_mount_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "not a real directory"):
                read_host_artifact(link)

    def test_rejects_path_like_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unsafe mounted artifact filename"):
                read_host_artifact(tmp, "../escape.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
