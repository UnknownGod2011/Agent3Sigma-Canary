#!/usr/bin/env python3
"""Assert that two artifact-handoff adapters preserve the same desktop run."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

RUNS = ("first", "repeat")
REPRODUCIBILITY_KEYS = (
    "final_state_bytes",
    "gui_action_sequence",
    "screenshots",
)
EVIDENCE_KEYS = (
    "state_sha256",
    "gui_action_sha256",
    "gui_actions",
    "screenshot_sha256",
)
METRIC_KEYS = (
    "score",
    "gui_action_count",
    "observation_count",
    "screenshot_read_count",
    "post_edit_observation_count",
    "verification_retry_count",
)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read handoff manifest {path}: {exc}") from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise ValueError(f"unsupported handoff manifest schema in {path}")
    for key in ("task_id", "mode", "upstream_master_sha", "task_definition_sha256"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"handoff manifest {path} has no valid {key}")
    if not _is_sha256(manifest["task_definition_sha256"]):
        raise ValueError(f"handoff manifest {path} has invalid task_definition_sha256")

    reproducible = manifest.get("reproducible")
    if not isinstance(reproducible, dict) or any(
        reproducible.get(key) is not True for key in REPRODUCIBILITY_KEYS
    ):
        raise ValueError(f"handoff manifest {path} is not internally reproducible")

    runs = manifest.get("runs")
    if not isinstance(runs, dict):
        raise ValueError(f"handoff manifest {path} has no run records")
    for run_name in RUNS:
        run = runs.get(run_name)
        if not isinstance(run, dict):
            raise ValueError(f"handoff manifest {path} is missing runs.{run_name}")
        for key in (*EVIDENCE_KEYS, *METRIC_KEYS):
            if key not in run:
                raise ValueError(f"handoff manifest {path} is missing runs.{run_name}.{key}")
        score = run["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score != 1.0:
            raise ValueError(
                f"handoff manifest {path} has no full automated score in runs.{run_name}"
            )
        if not _is_sha256(run["state_sha256"]):
            raise ValueError(f"handoff manifest {path} has invalid runs.{run_name}.state_sha256")
        if not _is_sha256(run["gui_action_sha256"]):
            raise ValueError(
                f"handoff manifest {path} has invalid "
                f"runs.{run_name}.gui_action_sha256"
            )
        if (
            not isinstance(run["gui_actions"], list)
            or not run["gui_actions"]
            or any(not isinstance(action, str) for action in run["gui_actions"])
        ):
            raise ValueError(f"handoff manifest {path} has invalid runs.{run_name}.gui_actions")
        if (
            not isinstance(run["screenshot_sha256"], list)
            or not run["screenshot_sha256"]
            or any(not _is_sha256(digest) for digest in run["screenshot_sha256"])
        ):
            raise ValueError(
                f"handoff manifest {path} has invalid "
                f"runs.{run_name}.screenshot_sha256"
            )
        for key in METRIC_KEYS[1:]:
            value = run[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"handoff manifest {path} has invalid "
                    f"runs.{run_name}.{key}"
                )
        if run["gui_action_count"] != len(run["gui_actions"]):
            raise ValueError(
                f"handoff manifest {path} has inconsistent "
                f"runs.{run_name}.gui_action_count"
            )
        if run["screenshot_read_count"] != len(run["screenshot_sha256"]):
            raise ValueError(
                f"handoff manifest {path} has inconsistent "
                f"runs.{run_name}.screenshot_read_count"
            )

    for key in (*EVIDENCE_KEYS, *METRIC_KEYS):
        if runs["first"][key] != runs["repeat"][key]:
            raise ValueError(f"handoff manifest {path} is not repeatable in {key}")
    return manifest


def compare_handoff_modes(first_path: Path, second_path: Path) -> dict[str, Any]:
    first = _load_manifest(first_path)
    second = _load_manifest(second_path)

    for key in (
        "schema_version",
        "task_id",
        "mode",
        "upstream_master_sha",
        "task_definition_sha256",
    ):
        if first.get(key) != second.get(key):
            raise ValueError(
                f"handoff manifests differ in {key}: "
                f"{first.get(key)!r} != {second.get(key)!r}"
            )

    for run_name in RUNS:
        left = first["runs"][run_name]
        right = second["runs"][run_name]
        for key in (*EVIDENCE_KEYS, *METRIC_KEYS):
            if left[key] != right[key]:
                raise ValueError(
                    f"handoff manifests differ in runs.{run_name}.{key}: "
                    f"{left[key]!r} != {right[key]!r}"
                )

    return {
        "schema_version": 2,
        "task_id": first["task_id"],
        "mode": first["mode"],
        "upstream_master_sha": first["upstream_master_sha"],
        "task_definition_sha256": first["task_definition_sha256"],
        "equivalent": True,
        "runs_compared": list(RUNS),
        "evidence_fields": list(EVIDENCE_KEYS),
        "metric_fields": list(METRIC_KEYS),
        "first_manifest": str(first_path),
        "second_manifest": str(second_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = compare_handoff_modes(args.first, args.second)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"desktop handoff equivalence check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
