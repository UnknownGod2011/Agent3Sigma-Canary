#!/usr/bin/env python3
"""Regression tests for provider-interruption versus benchmark-failure classification."""
from __future__ import annotations

from classify_model_attempt import classify


def main() -> None:
    agent_quota_error = (
        "2026-10-19T02:40:21Z [agent/embedded] embedded run agent end: "
        "runId=example isError=true model=gemini-3.6-flash provider=google "
        "error=API rate limit reached. Please try again later. rawError={code:429}"
    )
    verifier_failure = "error: desktop benchmark verification failed: full_grade, fail_closed_breakdown"

    cases = [
        (0, "desktop benchmark verified", "success"),
        (75, "Gemini slot transient HTTP 429; trying next configured slot", "transient_provider"),
        (1, "Traceback: SyntaxError", "other_failure"),
        (1, verifier_failure, "benchmark_failure"),
        # A provider error that actually terminated the target-agent run before
        # the verifier result makes this attempt unsuitable as model evidence.
        (1, f"{agent_quota_error}\n{verifier_failure}", "transient_provider"),
        # A later/generic quota string must not mask a failed evaluated trajectory.
        (1, f"{verifier_failure}\nGemini key slot hit provider capacity/quota", "benchmark_failure"),
        (1, f"{verifier_failure}\n{agent_quota_error}", "benchmark_failure"),
        (1, f"HTTP 429 provider warning\n{verifier_failure}", "benchmark_failure"),
    ]
    for exit_code, log, expected in cases:
        actual = classify(exit_code, log)
        assert actual == expected, (expected, actual, log)

    print(f"model attempt classification tests passed ({len(cases)} cases)")


if __name__ == "__main__":
    main()
