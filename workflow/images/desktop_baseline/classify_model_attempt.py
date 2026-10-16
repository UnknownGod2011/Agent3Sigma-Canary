#!/usr/bin/env python3
"""Classify failed live-model attempts without masking benchmark failures.

Provider capacity/transport errors may be retried with another configured key,
but an evaluated trajectory that fails the benchmark verifier is a task/model
failure even if an unrelated quota message also appears earlier in the log.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_TRANSIENT_PROVIDER = re.compile(
    r"HTTP\s+(?:429|500|502|503|504)\b|RESOURCE_EXHAUSTED|UNAVAILABLE|"
    r"high[- ]demand|rate.?limit|quota",
    re.IGNORECASE,
)
_BENCHMARK_FAILURE = re.compile(
    r"desktop benchmark verification failed",
    re.IGNORECASE,
)


def classify(exit_code: int, log: str) -> str:
    if exit_code == 0:
        return "success"
    # A terminal verifier failure means an artifact was produced and failed
    # the baseline gate. Do not let an earlier transient API error override it.
    if _BENCHMARK_FAILURE.search(log):
        return "benchmark_failure"
    if _TRANSIENT_PROVIDER.search(log):
        return "transient_provider"
    return "other_failure"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: classify_model_attempt.py EXIT_CODE LOG_PATH", file=sys.stderr)
        return 2
    try:
        exit_code = int(sys.argv[1])
        log = Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace")
    except (ValueError, OSError) as exc:
        print(f"error: cannot classify model attempt: {exc}", file=sys.stderr)
        return 2
    print(classify(exit_code, log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
