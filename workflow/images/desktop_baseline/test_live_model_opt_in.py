#!/usr/bin/env python3
"""Regression guard: live-model API usage must remain explicit opt-in."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-baseline-smoke.yml"

def job_body(source: str, name: str) -> str:
    start = re.search(rf"(?m)^  {re.escape(name)}:[ \\t]*$", source)
    assert start, f"missing workflow job: {name}"
    body_start = start.end()
    next_job = re.search(r"(?m)^  [A-Za-z0-9_-]+:[ \\t]*$", source[body_start:])
    body_end = body_start + next_job.start() if next_job else len(source)
    return source[body_start:body_end]

def main() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    smoke = job_body(source, "desktop-smoke")
    model = job_body(source, "gemini-model-e2e")
    expected = "${{ github.event_name == 'workflow_dispatch' || (github.event_name == 'push' && contains(github.event.head_commit.message, '[run-live-model]')) }}"
    condition = re.search(r"(?m)^    if:[ \\t]*(.+)$", model)
    assert condition and condition.group(1).strip() == expected, (
        "live-model evaluation must require manual dispatch or the explicit [run-live-model] marker",
        condition.group(1).strip() if condition else None,
    )
    assert "GEMINI_API_KEY_" not in smoke, "API key environment leaked into deterministic smoke job"
    assert "GEMINI_API_KEY_1: ${{ secrets.GEMINI_API_KEY }}" in model
    assert "Run evaluated Gemini desktop baseline with failover" in model
    assert "Run evaluated Gemini desktop baseline with failover" not in smoke
    print("live-model opt-in workflow regression test passed")

if __name__ == "__main__":
    main()
