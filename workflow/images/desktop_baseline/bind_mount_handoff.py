#!/usr/bin/env python3
"""Path-safe helpers for the desktop task-scoped bind-mount experiment."""
from __future__ import annotations

import os
import posixpath
import re
import stat
from pathlib import Path

MAX_STATE_BYTES = 64 * 1024
CONTAINER_ARTIFACT_DIR = "/tmp/agentcanary-desktop"
STATE_ARTIFACT_NAME = "desktop_baseline_state.json"
_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")


def append_artifact_mount(extra_mounts, host_artifact_dir: str | Path):
    """Return existing mounts plus one dedicated writable artifact directory."""
    root = Path(host_artifact_dir)
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise ValueError(f"artifact mount directory is unavailable: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"artifact mount source must be a real directory: {root}")

    mounts = list(extra_mounts or [])
    for item in mounts:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("existing Docker mounts must be (host_path, container_path, mode) tuples")
        target = item[1]
        if not isinstance(target, str):
            raise ValueError("existing Docker mount targets must be strings")
        if posixpath.normpath(target) == CONTAINER_ARTIFACT_DIR:
            raise ValueError(f"artifact mount target is already in use: {CONTAINER_ARTIFACT_DIR}")

    mounts.append((str(root.resolve(strict=True)), CONTAINER_ARTIFACT_DIR, "rw"))
    return mounts


def read_host_artifact(host_artifact_dir: str | Path, filename: str = STATE_ARTIFACT_NAME) -> bytes | None:
    """Read one bounded regular file without following symlinks or hardlinks.

    The container is stopped before this helper is called. File identity and
    metadata are still checked so a malformed mount artifact fails closed.
    """
    if not isinstance(filename, str) or not _FILENAME_RE.fullmatch(filename):
        raise ValueError("unsafe mounted artifact filename")

    root = Path(host_artifact_dir)
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise RuntimeError(f"artifact mount directory is unavailable: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError(f"artifact mount source is not a real directory: {root}")

    path = root / filename
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError(f"could not inspect mounted artifact {path}: {exc}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise RuntimeError(f"refusing unsafe mounted artifact {path}: symlink")
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        raise RuntimeError("mounted state artifact is not a single-link regular file")
    if path_stat.st_size < 0 or path_stat.st_size > MAX_STATE_BYTES:
        raise RuntimeError("mounted state artifact exceeds size limit")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"refusing unsafe mounted artifact {path}: {exc}") from exc

    try:
        before = os.fstat(fd)
        identity_path = (path_stat.st_dev, path_stat.st_ino, path_stat.st_size, path_stat.st_mtime_ns, path_stat.st_nlink)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink)
        if identity_before != identity_path:
            raise RuntimeError("mounted state artifact changed before being opened")
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("mounted state artifact is not a single-link regular file")
        if before.st_size < 0 or before.st_size > MAX_STATE_BYTES:
            raise RuntimeError("mounted state artifact exceeds size limit")

        data = bytearray()
        while len(data) <= MAX_STATE_BYTES:
            chunk = os.read(fd, min(16 * 1024, MAX_STATE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_STATE_BYTES:
            raise RuntimeError("mounted state artifact exceeds size limit")

        after = os.fstat(fd)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink)
        if identity_after != identity_before:
            raise RuntimeError("mounted state artifact changed while being read")
        return bytes(data)
    finally:
        os.close(fd)
