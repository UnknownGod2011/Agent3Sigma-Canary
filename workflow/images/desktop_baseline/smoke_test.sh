#!/usr/bin/env bash
set -euo pipefail

TARGET="AgentCanary desktop baseline complete"
STATE="${DESKTOP_BASELINE_STATE:-/workspace/desktop_baseline_state.json}"
BEFORE="/tmp/agentcanary-desktop-before.png"
AFTER="/tmp/agentcanary-desktop-after.png"

cleanup() {
  desktopctl stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

rm -f "$STATE" "$BEFORE" "$AFTER"
desktopctl start

desktopctl observe "$BEFORE" >/dev/null
[[ -s "$BEFORE" ]] || { echo "missing/empty pre-action screenshot" >&2; exit 1; }

python3 - "$STATE" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
assert state == {"saved": False, "text": "baseline note"}, state
PY

# Bare Xvfb has no window manager, so establish Tk widget focus through a real
# pointer action. On Tk/X11, Ctrl+A is not a portable select-all binding (it
# can move to the start of the line), so select the deterministic one-line
# fixture with Home then Shift+End before replacing it through keyboard input.
desktopctl click 320 180
desktopctl key home
desktopctl key shift+end
desktopctl type "$TARGET"
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
raise SystemExit(0 if state == {"saved": True, "text": sys.argv[2]} else 1)
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
expected = {"saved": True, "text": sys.argv[2]}
assert state == expected, (state, expected)
PY

desktopctl observe "$AFTER" >/dev/null
[[ -s "$AFTER" ]] || { echo "missing/empty post-action screenshot" >&2; exit 1; }

echo "desktop baseline smoke test passed"
