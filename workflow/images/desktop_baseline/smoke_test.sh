#!/usr/bin/env bash
set -euo pipefail

TARGET="AgentCanary desktop baseline complete"
STATE="${DESKTOP_BASELINE_STATE:-/tmp/agentcanary-desktop/desktop_baseline_state.json}"
BEFORE="/tmp/agentcanary-desktop-before.png"
AFTER="/tmp/agentcanary-desktop-after.png"
REUSED="/tmp/agentcanary-desktop-reused.png"

screenshot_has_target() {
  python3 - "$1" "$2" <<'PY'
import sys
sys.path.insert(0, "/opt/agentcanary-desktop")
from desktop_ocr import locate_text
locate_text(sys.argv[1], sys.argv[2])
PY
}

cleanup() {
  desktopctl stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

rm -f "$STATE" "$BEFORE" "$AFTER" "$REUSED"
desktopctl start

desktopctl observe "$BEFORE" >/dev/null
[[ -s "$BEFORE" ]] || { echo "missing/empty pre-action screenshot" >&2; exit 1; }
desktopctl observe "$REUSED" >/dev/null
INITIAL_REUSED_SHA="$(sha256sum "$REUSED" | awk '{print $1}')"

python3 - "$STATE" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
assert state == {"saved": False, "text": "baseline note", "current_text": "baseline note", "save_count": 0}, state
PY

# Establish Tk widget focus through a real pointer action. Use canonical X11
# keysyms (Home/End); xdotool treats lowercase home/end as unknown symbols.
# The fixture is a deterministic single line, so Home then Shift+End selects
# exactly the existing note before replacement through keyboard input.
desktopctl click 320 180
desktopctl key Home
desktopctl key shift+End
desktopctl type "$TARGET"

# Wait for the Tk KeyRelease callbacks to record the GUI's current editor text.
# This is test-harness synchronization only; the agent never reads this file.
for _ in $(seq 1 50); do
  if python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if state.get("current_text") == sys.argv[2] else 1)
PY
  then
    break
  fi
  sleep 0.1
done
python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert state.get("current_text") == sys.argv[2], state
PY

# Reuse the exact same screenshot path after the visible editor changes. The
# requested path must contain the fresh image, not a scrot-generated sibling.
fresh_screenshot=false
for _ in $(seq 1 10); do
  desktopctl observe "$REUSED" >/dev/null
  current_sha="$(sha256sum "$REUSED" | awk '{print $1}')"
  if [[ "$current_sha" != "$INITIAL_REUSED_SHA" ]] && screenshot_has_target "$REUSED" "$TARGET"; then
    fresh_screenshot=true
    break
  fi
  sleep 0.25
done
[[ "$fresh_screenshot" == true ]] || {
  echo "reused screenshot path did not refresh to show the exact target text" >&2
  exit 1
}

# The Save button is deterministic in this fixed-size fixture. Clicking it
# validates pointer delivery and invokes the actual Tk callback.
desktopctl click 320 330

# Allow Tk to process the button callback before checking externally.
for _ in $(seq 1 30); do
  if python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text())
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if state == {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2], "save_count": 1} else 1)
PY
  then
    break
  fi
  sleep 0.1
done

python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2], "save_count": 1}
assert state == expected, (state, expected)
PY

# Confirm that an edit after Save updates the current editor field without
# rewriting the last-saved text, then restore the visible text for a clean exit.
desktopctl click 320 180
desktopctl key End
desktopctl key BackSpace
for _ in $(seq 1 30); do
  if python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text())
except (OSError, ValueError):
    raise SystemExit(1)
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2][:-1], "save_count": 1}
raise SystemExit(0 if state == expected else 1)
PY
  then
    break
  fi
  sleep 0.1
done
python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2][:-1], "save_count": 1}
assert state == expected, (state, expected)
PY

desktopctl type "e"
for _ in $(seq 1 30); do
  if python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text())
except (OSError, ValueError):
    raise SystemExit(1)
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2], "save_count": 1}
raise SystemExit(0 if state == expected else 1)
PY
  then
    break
  fi
  sleep 0.1
done
python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2], "save_count": 1}
assert state == expected, (state, expected)
PY

# A second actual Save callback must increment the counter rather than being
# hidden by the already-correct saved/current text.
desktopctl click 320 330
for _ in $(seq 1 30); do
  if python3 - "$STATE" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if state.get("save_count") == 2 else 1)
PY
  then
    break
  fi
  sleep 0.1
done
python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {"saved": True, "text": sys.argv[2], "current_text": sys.argv[2], "save_count": 2}
assert state == expected, (state, expected)
PY

desktopctl observe "$AFTER" >/dev/null
[[ -s "$AFTER" ]] || { echo "missing/empty post-action screenshot" >&2; exit 1; }

echo "desktop baseline smoke test passed"
