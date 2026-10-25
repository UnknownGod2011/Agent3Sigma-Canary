#!/usr/bin/env python3
"""Guard the desktop CI triggers against omitted staged image dependencies."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = (
    Path(".github/workflows/desktop-baseline-smoke.yml"),
    Path(".github/workflows/desktop-reference-lifecycle.yml"),
)
REQUIRED_PATHS = {
    "workflow/images/desktop_baseline/**",
    "tasks/desktop_baseline/**",
    "benchmark.py",
    "scripts/**",
    "workflow/images/official/**",
    "assets/mock_api/**",
    "pyproject.toml",
    "uv.lock",
    "setup.sh",
}


def configured_push_paths(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^    paths:\n(?P<block>(?:^      - .*\n)+)", source)
    assert match, f"{path}: missing push.paths filter"
    return set(re.findall(r'^      - "([^"]+)"$', match.group("block"), re.MULTILINE))


def main() -> None:
    for relative_path in WORKFLOWS:
        workflow_path = ROOT / relative_path
        configured = configured_push_paths(workflow_path)
        required = REQUIRED_PATHS | {relative_path.as_posix()}
        missing = sorted(required - configured)
        assert not missing, f"{relative_path}: missing trigger paths: {missing}"
        print(f"{relative_path}: required source paths covered")
    print("desktop CI trigger dependency checks passed")


if __name__ == "__main__":
    main()
