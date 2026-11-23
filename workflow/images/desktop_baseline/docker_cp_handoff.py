#!/usr/bin/env python3
"""Copy one allowlisted task artifact from Docker before container teardown.

The Docker CLI copies only the fixed grader-state path into a fresh host-owned
staging directory. The staged file is then validated with the same no-follow,
regular-file, single-link, size-bounded reader used by the bind-mount experiment.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

from bind_mount_handoff import (
    CONTAINER_ARTIFACT_DIR,
    STATE_ARTIFACT_NAME,
    read_host_artifact,
)

CONTAINER_STATE_PATH = f"{CONTAINER_ARTIFACT_DIR}/{STATE_ARTIFACT_NAME}"
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}\Z")


def copy_container_artifact(
    container_id: str,
    staging_dir: str | Path,
    *,
    timeout: float = 15,
) -> bytes | None:
    """Copy the fixed state file to staging and return validated bytes.

    No caller-controlled source path or destination filename is accepted. A
    missing/unreadable source fails closed by raising rather than returning an
    empty artifact that could be mistaken for a successful handoff.
    """
    if not isinstance(container_id, str) or not _CONTAINER_ID_RE.fullmatch(container_id):
        raise ValueError("container id must be a full hexadecimal Docker id")

    root = Path(staging_dir)
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise ValueError(f"staging directory is unavailable: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("staging directory must be a real directory")

    destination = root / STATE_ARTIFACT_NAME
    try:
        os.lstat(destination)
    except FileNotFoundError:
        pass
    else:
        raise ValueError("staging artifact destination must not already exist")

    try:
        result = subprocess.run(
            ["docker", "cp", f"{container_id}:{CONTAINER_STATE_PATH}", str(destination)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"docker cp timed out after {timeout}s") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"docker cp failed (exit {result.returncode}): {detail}")

    return read_host_artifact(root, STATE_ARTIFACT_NAME)
