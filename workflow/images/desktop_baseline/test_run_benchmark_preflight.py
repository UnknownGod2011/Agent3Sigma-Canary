#!/usr/bin/env python3
"""Regression tests for the desktop runner's placeholder-config guard."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workflow" / "images" / "desktop_baseline" / "run_benchmark.sh"
SOURCE = SCRIPT.read_text(encoding="utf-8")
MATCH = re.search(
    r"grep\s+-Eq\s+'([^']+)'\s+workflow/images/official/openclaw\.json",
    SOURCE,
)
assert MATCH, "could not locate the live-runner placeholder guard"
PATTERN = MATCH.group(1)


def is_placeholder(value: str) -> bool:
    result = subprocess.run(
        ["grep", "-Eq", PATTERN],
        input=value + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def main() -> None:
    placeholders = (
        "your-api-key-here",
        "sk-your-key-here",
        "sk-ant-your-key-here",
        "https://api.example.com/v1",
    )
    for value in placeholders:
        assert is_placeholder(value), f"placeholder was not rejected: {value}"

    valid_values = (
        "https://generativelanguage.googleapis.com/v1beta",
        "https://api.openai.com/v1",
        "sk-live-not-placeholder",
    )
    for value in valid_values:
        assert not is_placeholder(value), f"valid config value was rejected: {value}"

    print("desktop runner placeholder preflight tests passed (7 cases)")


if __name__ == "__main__":
    main()
