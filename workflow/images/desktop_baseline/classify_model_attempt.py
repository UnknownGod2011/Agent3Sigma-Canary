#!/usr/bin/env python3
"""Classify model attempts without mislabeling provider interruptions as model failures.

A target-agent run explicitly ending with a transient provider error before the
terminal verifier result is an interrupted attempt and may be retried. A generic
quota message that appears only after a failed trajectory must not mask it.
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
_AGENT_PROVIDER_INTERRUPTION = re.compile(
    r"\[agent/embedded\].*?embedded run agent end:.*?isError=true.*?"
    r"(?:HTTP\s*(?:429|500|502|503|504)\b|RESOURCE_EXHAUSTED|UNAVAILABLE|"
    r"high[- ]demand|rate.?limit|quota)",
    re.IGNORECASE,
)


def classify(exit_code: int, log: str) -> str:
    if exit_code == 0:
        return "success"

    benchmark_failure = _BENCHMARK_FAILURE.search(log)
    if benchmark_failure:
        # Retry only when the target agent itself ended with a transient
        # provider error before the failed artifact was graded. This avoids
        # treating quota-interrupted trajectories as model evidence while also
        # preventing later/generic quota text from hiding a real task failure.
        provider_interruption = _AGENT_PROVIDER_INTERRUPTION.search(log)
        if provider_interruption and provider_interruption.start() < benchmark_failure.start():
            return "transient_provider"
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
