#!/usr/bin/env python3
"""Run the desktop baseline using Docker CLI artifact copyback."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import run_reference_benchmark as baseline  # noqa: E402
from docker_cp_handoff import copy_container_artifact  # noqa: E402


def _copy_grader_state_artifact_to_host(container_id: str, host_workspace: Path) -> bool:
    """Use docker cp, then validate and atomically copy the fixed artifact."""
    try:
        with tempfile.TemporaryDirectory(prefix="agentcanary-desktop-docker-cp-") as staging:
            data = copy_container_artifact(container_id, staging)
    except RuntimeError as exc:
        print(f"Docker CLI artifact export failed; host grading will fail closed: {exc}", flush=True)
        data = None

    copied = baseline.safe_export.write_state_artifact(
        host_workspace,
        data,
        baseline.STATE_ARTIFACT_NAME,
    )
    if copied:
        print(
            "Preserved grader-only desktop state artifact via docker cp outside agent workspace: "
            f"{host_workspace / baseline.STATE_ARTIFACT_NAME}",
            flush=True,
        )
    else:
        print("Docker cp produced no validated grader artifact; host grading will fail closed", flush=True)
    return copied


def install_docker_cp_exporter() -> None:
    """Replace only the research wrapper's artifact reader, not the benchmark lifecycle."""
    baseline._copy_grader_state_artifact_to_host = _copy_grader_state_artifact_to_host


def main() -> None:
    install_docker_cp_exporter()
    baseline.main()


if __name__ == "__main__":
    main()
