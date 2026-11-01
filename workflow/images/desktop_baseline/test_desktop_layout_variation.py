#!/usr/bin/env python3
"""Exercise the real X11/Tk task at two window origins using screenshot OCR."""
from __future__ import annotations

import json
import os
import subprocess
import sys

IMAGE = os.environ.get("DESKTOP_BASELINE_IMAGE", "agentcanary-desktop-baseline")
PROBE = r'''
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/agentcanary-desktop")
from desktop_ocr import locate_text


def run(*args):
    return subprocess.run(
        list(args), capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()


state_path = Path("/tmp/agentcanary-desktop/layout_probe_state.json")
before_path = Path("/tmp/agentcanary-desktop/layout_probe_before.png")
after_path = Path("/tmp/agentcanary-desktop/layout_probe_after.png")
target = "AgentCanary desktop baseline complete"

run("desktopctl", "observe", str(before_path))
editor = locate_text(before_path, "baseline note")
run("desktopctl", "click", str(editor[0]), str(editor[1]))
run("desktopctl", "key", "Home")
run("desktopctl", "key", "shift+End")
run("desktopctl", "type", target)
run("desktopctl", "observe", str(after_path))
save = locate_text(after_path, "Save")
run("desktopctl", "click", str(save[0]), str(save[1]))

state = None
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        time.sleep(0.1)
        continue
    if state.get("saved") is True:
        break
    time.sleep(0.1)
assert state == {"current_text": target, "saved": True, "text": target}, state
print(json.dumps({"editor": editor, "save": save, "state": state}, sort_keys=True))
'''


def docker(*args: str, timeout: int = 45, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"docker {' '.join(args)} failed: {detail}")
    return result


def run_case(label: str, origin: tuple[int, int]) -> dict:
    name = f"agentcanary-desktop-layout-{os.getpid()}-{label}"
    docker("run", "-d", "--name", name, IMAGE, timeout=60)
    try:
        state_path = "/tmp/agentcanary-desktop/layout_probe_state.json"
        docker("exec", name, "desktopctl", "start", state_path)
        if origin != (40, 40):
            window = docker(
                "exec", name, "xdotool", "search", "--onlyvisible", "--name",
                "AgentCanary Desktop Baseline",
            ).stdout.splitlines()
            if len(window) != 1:
                raise AssertionError(f"expected one visible desktop window, found {window}")
            docker("exec", name, "xdotool", "windowmove", window[0], str(origin[0]), str(origin[1]))
            docker("exec", name, "sleep", "0.5")
        result = docker("exec", name, "python3", "-c", PROBE, timeout=45)
        return json.loads(result.stdout)
    finally:
        docker("rm", "-f", name, timeout=30, check=False)


def main() -> int:
    baseline = run_case("baseline", (40, 40))
    moved = run_case("moved", (140, 120))
    for target_name in ("editor", "save"):
        before = baseline[target_name]
        after = moved[target_name]
        delta = (after[0] - before[0], after[1] - before[1])
        if abs(delta[0] - 100) > 2 or abs(delta[1] - 80) > 2:
            raise AssertionError(
                f"{target_name} OCR coordinate did not follow the moved GUI window: "
                f"before={before}, after={after}, delta={delta}"
            )
    print(json.dumps({"baseline": baseline, "moved": moved, "verified_delta": [100, 80]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
