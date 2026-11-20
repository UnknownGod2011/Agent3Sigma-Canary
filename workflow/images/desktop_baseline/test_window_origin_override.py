#!/usr/bin/env python3
"""Regression tests for the optional desktop window-origin integration probe."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_reference_benchmark as runner  # noqa: E402


def _reject(argv: list[str]) -> None:
    try:
        runner._extract_window_origin(argv)
    except SystemExit:
        return
    raise AssertionError(f"invalid window-origin arguments were accepted: {argv!r}")


def main() -> int:
    argv = ["runner.py", "--model", "desktop-stub/desktop-fixture",
            "--window-origin", "40,40", "--docker"]
    assert runner._extract_window_origin(argv) == (40, 40)
    assert argv == ["runner.py", "--model", "desktop-stub/desktop-fixture", "--docker"]

    equals_form = ["runner.py", "--window-origin=160,240"]
    assert runner._extract_window_origin(equals_form) == (160, 240)
    assert equals_form == ["runner.py"]
    assert runner._extract_window_origin(["runner.py", "--docker"]) is None

    _reject(["runner.py", "--window-origin"])
    _reject(["runner.py", "--window-origin", "40"])
    _reject(["runner.py", "--window-origin", "-1,0"])
    _reject(["runner.py", "--window-origin", "40,40,1"])
    _reject(["runner.py", "--window-origin", "161,240"])
    _reject(["runner.py", "--window-origin", "160,241"])
    _reject(["runner.py", "--window-origin", "40,40", "--window-origin", "40,40"])

    print("desktop window-origin option validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
