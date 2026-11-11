#!/usr/bin/env python3
"""Exercise the real X11/Tk task at two window origins using screenshot OCR."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE = os.environ.get("DESKTOP_BASELINE_IMAGE", "agentcanary-desktop-baseline")
DIAGNOSTICS_ROOT = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "desktop-layout-diagnostics"
PROBE = r'''
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/agentcanary-desktop")
from desktop_ocr import locate_save_button, locate_text


def run(*args):
    result = subprocess.run(
        list(args), capture_output=True, text=True, check=False, timeout=20
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"desktop command {args!r} exited {result.returncode}: {detail}"
        )
    return result.stdout.strip()


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

# Wait for the GUI's KeyRelease callback to publish the final editor contents
# before taking the screenshot used for coordinate verification.
deadline = time.monotonic() + 5
state = None
while time.monotonic() < deadline:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        time.sleep(0.1)
        continue
    if state.get("current_text") == target:
        break
    time.sleep(0.1)
assert state and state.get("current_text") == target, state
run("desktopctl", "observe", str(after_path))
save = locate_save_button(after_path)
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


def _capture_diagnostics(container: str, label: str) -> None:
    """Preserve the failing container's screenshot and X11/Tk evidence before cleanup."""
    destination = DIAGNOSTICS_ROOT / label
    destination.mkdir(parents=True, exist_ok=True)
    probes = {
        "container-logs.txt": ["logs", container],
        "processes.txt": ["exec", container, "ps", "-ef"],
        "window-tree.txt": ["exec", container, "xwininfo", "-root", "-tree"],
        "display.txt": ["exec", container, "xdpyinfo", "-display", ":99"],
        "app.log": ["exec", container, "cat", "/tmp/agentcanary-desktop/app.log"],
        "xvfb.log": ["exec", container, "cat", "/tmp/agentcanary-desktop/xvfb.log"],
        "before-ocr.tsv": [
            "exec", container, "tesseract",
            "/tmp/agentcanary-desktop/layout_probe_before.png",
            "stdout", "--psm", "11", "tsv",
        ],
        "after-ocr.tsv": [
            "exec", container, "tesseract",
            "/tmp/agentcanary-desktop/layout_probe_after.png",
            "stdout", "--psm", "11", "tsv",
        ],
    }
    for filename, args in probes.items():
        try:
            result = docker(*args, timeout=15, check=False)
            body = result.stdout or ""
            if result.stderr:
                body += "\n[stderr]\n" + result.stderr
            if result.returncode:
                body += f"\n[exit_code={result.returncode}]\n"
            (destination / filename).write_text(body, encoding="utf-8")
        except Exception as exc:
            (destination / filename).write_text(
                f"diagnostic command failed: {type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )

    for filename in ("layout_probe_before.png", "layout_probe_after.png"):
        source = f"{container}:/tmp/agentcanary-desktop/{filename}"
        try:
            result = docker("cp", source, str(destination / filename), timeout=20, check=False)
            if result.returncode:
                (destination / f"{filename}.missing.txt").write_text(
                    (result.stderr or result.stdout or "docker cp failed").strip() + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            (destination / f"{filename}.missing.txt").write_text(
                f"diagnostic copy failed: {type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
    print(f"Preserved desktop layout diagnostics under {destination}", file=sys.stderr)


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
    except Exception:
        _capture_diagnostics(name, label)
        raise
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
