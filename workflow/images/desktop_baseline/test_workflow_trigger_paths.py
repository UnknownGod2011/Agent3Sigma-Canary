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
COMPATIBILITY_WORKFLOW = Path(".github/workflows/desktop-pr1-compatibility.yml")
RESEARCH_LOG_EXCLUSION = "!workflow/images/desktop_baseline/RESEARCH_LOG.md"
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
    return re.findall(r'^      - "([^"]+)"

def main() -> None:
    for relative_path in WORKFLOWS:
        workflow_path = ROOT / relative_path
        configured_paths = configured_push_paths(workflow_path)
        configured = set(configured_paths)
        required = REQUIRED_PATHS | {relative_path.as_posix()}
        missing = sorted(required - configured)
        assert not missing, f"{relative_path}: missing trigger paths: {missing}"
        assert RESEARCH_LOG_EXCLUSION in configured_paths, (
            f"{relative_path}: log-only edits must not trigger Docker integration workflows"
        )
        assert configured_paths.index("workflow/images/desktop_baseline/**") < configured_paths.index(RESEARCH_LOG_EXCLUSION), (
            f"{relative_path}: the research-log exclusion must follow the positive source path"
        )
        print(f"{relative_path}: required source paths covered; research-log-only edits excluded")
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
        '"schema_version": 2',
        '"repository": os.environ.get("GITHUB_REPOSITORY", "")',
        '"commit_sha": os.environ.get("GITHUB_SHA", "")',
        '"ref": os.environ.get("GITHUB_REF", "")',
        '"workflow": os.environ.get("GITHUB_WORKFLOW", "")',
        '"run_id": os.environ.get("GITHUB_RUN_ID", "")',
        '"run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "")',
        '"event_name": os.environ.get("GITHUB_EVENT_NAME", "")',
        '"task_definition_sha256": hashlib.sha256(task_definition.read_bytes()).hexdigest()',
        '"tool_sequence_sha256": tool_digest',
        '"action_sequence_sha256": action_digest',
        '"observation_count": observation_count',
        '"reobservation_count": observation_count - 2',
    ):
        assert field in lifecycle_source, f"evidence manifest missing provenance field: {field}"
    print("desktop evidence manifest records source, run, and task-definition provenance")
    print("desktop grader-only state evidence retention is configured")

    compatibility_path = ROOT / COMPATIBILITY_WORKFLOW
    compatibility_paths = configured_push_paths(compatibility_path)
    compatibility_required = {
        ".github/workflows/desktop-pr1-compatibility.yml",
        "workflow/images/desktop_baseline/**",
        "tasks/desktop_baseline/**",
    }
    compatibility_missing = sorted(compatibility_required - set(compatibility_paths))
    assert not compatibility_missing, (
        f"{COMPATIBILITY_WORKFLOW}: missing trigger paths: {compatibility_missing}"
    )
    assert RESEARCH_LOG_EXCLUSION in compatibility_paths, (
        "compatibility workflow must exclude research-log-only changes"
    )
    assert compatibility_paths.index("workflow/images/desktop_baseline/**") < compatibility_paths.index(RESEARCH_LOG_EXCLUSION), (
        "compatibility workflow log exclusion must follow the positive source path"
    )
    print("compatibility workflow excludes research-log-only changes")
    compatibility_source = compatibility_path.read_text(encoding="utf-8")
    assert 'git -C "$RUNNER_TEMP/upstream-master" fetch --depth=1 origin refs/heads/master' in compatibility_source, (
        "desktop compatibility must fetch the current upstream master, not a historical PR ref"
    )
    assert "UPSTREAM_MASTER_SHA" in compatibility_source, "compatibility evidence must record the tested upstream master SHA"
    assert "refs/pull/1/head" not in compatibility_source, "compatibility must not remain pinned to PR #1"

    native_bind_mount_step = (
        "      - name: Run task-scoped bind-mount OpenClaw tool loop twice on upstream runner"
    )
    assert native_bind_mount_step in compatibility_source, (
        "native OpenClaw bind-mount experiment must run against the current upstream runner"
    )
    assert "Verify task-scoped bind-mount handoff with native OpenClaw CLI (repeat twice)" not in lifecycle_source, (
        "the stale fork runner must not own the native OpenClaw CLI integration gate"
    )
    step_start = compatibility_source.index(native_bind_mount_step)
    step_end = compatibility_source.find("\\n      - name:", step_start + len(native_bind_mount_step))
    native_step = compatibility_source[step_start:step_end if step_end >= 0 else None]
    for required in (
        "DOCKER_IMAGE=agentcanary-desktop-upstream-openclaw-stub",
        "run_bind_mount_benchmark.py",
        "--model desktop-stub/desktop-fixture",
        "upstream-bind-mount-openclaw-stub-$attempt",
        'value.startswith("desktop-reference-")',
    ):
        assert required in native_step, f"native OpenClaw bind-mount experiment missing: {required}"
    print("native OpenClaw bind-mount experiment is part of the upstream compatibility gate")
    print("desktop compatibility workflow tracks current upstream master")
    print("desktop CI trigger dependency checks passed")


if __name__ == "__main__":
    main()
, match.group("block"), re.MULTILINE)


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
        '"schema_version": 2',
        '"repository": os.environ.get("GITHUB_REPOSITORY", "")',
        '"commit_sha": os.environ.get("GITHUB_SHA", "")',
        '"ref": os.environ.get("GITHUB_REF", "")',
        '"workflow": os.environ.get("GITHUB_WORKFLOW", "")',
        '"run_id": os.environ.get("GITHUB_RUN_ID", "")',
        '"run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "")',
        '"event_name": os.environ.get("GITHUB_EVENT_NAME", "")',
        '"task_definition_sha256": hashlib.sha256(task_definition.read_bytes()).hexdigest()',
        '"tool_sequence_sha256": tool_digest',
        '"action_sequence_sha256": action_digest',
        '"observation_count": observation_count',
        '"reobservation_count": observation_count - 2',
    ):
        assert field in lifecycle_source, f"evidence manifest missing provenance field: {field}"
    print("desktop evidence manifest records source, run, and task-definition provenance")
    print("desktop grader-only state evidence retention is configured")

    compatibility_path = ROOT / ".github" / "workflows" / "desktop-pr1-compatibility.yml"
    compatibility_source = compatibility_path.read_text(encoding="utf-8")
    assert 'git -C "$RUNNER_TEMP/upstream-master" fetch --depth=1 origin refs/heads/master' in compatibility_source, (
        "desktop compatibility must fetch the current upstream master, not a historical PR ref"
    )
    assert "UPSTREAM_MASTER_SHA" in compatibility_source, "compatibility evidence must record the tested upstream master SHA"
    assert "refs/pull/1/head" not in compatibility_source, "compatibility must not remain pinned to PR #1"

    native_bind_mount_step = (
        "      - name: Run task-scoped bind-mount OpenClaw tool loop twice on upstream runner"
    )
    assert native_bind_mount_step in compatibility_source, (
        "native OpenClaw bind-mount experiment must run against the current upstream runner"
    )
    assert "Verify task-scoped bind-mount handoff with native OpenClaw CLI (repeat twice)" not in lifecycle_source, (
        "the stale fork runner must not own the native OpenClaw CLI integration gate"
    )
    step_start = compatibility_source.index(native_bind_mount_step)
    step_end = compatibility_source.find("\\n      - name:", step_start + len(native_bind_mount_step))
    native_step = compatibility_source[step_start:step_end if step_end >= 0 else None]
    for required in (
        "DOCKER_IMAGE=agentcanary-desktop-upstream-openclaw-stub",
        "run_bind_mount_benchmark.py",
        "--model desktop-stub/desktop-fixture",
        "upstream-bind-mount-openclaw-stub-$attempt",
        'value.startswith("desktop-reference-")',
    ):
        assert required in native_step, f"native OpenClaw bind-mount experiment missing: {required}"
    print("native OpenClaw bind-mount experiment is part of the upstream compatibility gate")
    print("desktop compatibility workflow tracks current upstream master")
    print("desktop CI trigger dependency checks passed")


if __name__ == "__main__":
    main()
