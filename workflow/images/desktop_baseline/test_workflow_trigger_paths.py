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
    lifecycle_path = ROOT / ".github" / "workflows" / "desktop-reference-lifecycle.yml"
    lifecycle_source = lifecycle_path.read_text(encoding="utf-8")
    verify_step = "      - name: Verify and package grader-only desktop state evidence"
    upload_step = "      - name: Upload deterministic desktop lifecycle evidence"
    assert verify_step in lifecycle_source, "missing grader-only state evidence validation step"
    assert upload_step in lifecycle_source, "missing deterministic result artifact upload step"
    assert lifecycle_source.index(verify_step) < lifecycle_source.index(upload_step), (
        "state evidence must be validated and staged before artifact upload"
    )
    assert "${{ runner.temp }}/desktop-state-evidence/**" in lifecycle_source, (
        "grader-only state evidence must be retained with the task result JSONs"
    )
    for field in (
        '"schema_version": 1',
        '"repository": os.environ.get("GITHUB_REPOSITORY", "")',
        '"commit_sha": os.environ.get("GITHUB_SHA", "")',
        '"ref": os.environ.get("GITHUB_REF", "")',
        '"workflow": os.environ.get("GITHUB_WORKFLOW", "")',
        '"run_id": os.environ.get("GITHUB_RUN_ID", "")',
        '"run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "")',
        '"event_name": os.environ.get("GITHUB_EVENT_NAME", "")',
        '"task_definition_sha256": hashlib.sha256(task_definition.read_bytes()).hexdigest()',
    ):
        assert field in lifecycle_source, f"evidence manifest missing provenance field: {field}"
    print("desktop evidence manifest records source, run, and task-definition provenance")
    print("desktop grader-only state evidence retention is configured")
    print("desktop CI trigger dependency checks passed")


if __name__ == "__main__":
    main()
