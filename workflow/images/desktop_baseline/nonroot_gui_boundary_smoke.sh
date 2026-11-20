#!/usr/bin/env bash
set -euo pipefail

STATE="/tmp/agentcanary-desktop/desktop_baseline_state.json"
STATE_DIR="$(dirname "$STATE")"
AGENT_RUNTIME="/tmp/agentcanary-desktop-agent"
BEFORE="$AGENT_RUNTIME/before.png"
AFTER="$AGENT_RUNTIME/after.png"
TARGET="AgentCanary non-root GUI boundary check"
SOURCE="/opt/agentcanary-desktop/notes_ui.py"

cleanup() {
  xhost -SI:localuser:node >/dev/null 2>&1 || true
  desktopctl stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

command -v runuser >/dev/null
command -v xhost >/dev/null
id node >/dev/null

# Reset the fixture as root, then keep grader state and fixture source unreadable
# to the unprivileged GUI client. The agent receives a separate writable
# screenshot directory; it never needs access to the state directory.
desktopctl stop >/dev/null 2>&1 || true
rm -rf "$STATE_DIR" "$AGENT_RUNTIME"
umask 077
install -d -m 0700 "$STATE_DIR"
install -d -o node -g node -m 0700 "$AGENT_RUNTIME"
[[ "$(stat -c '%a' "$STATE_DIR")" == "700" ]]
[[ "$(stat -c '%a' "$SOURCE")" == "600" ]]

desktopctl start
# Re-enable X11 access control and grant only the dedicated local GUI user.
xhost - >/dev/null
xhost +SI:localuser:node >/dev/null

as_node() {
  runuser -u node -- env \
    DISPLAY=:99 \
    HOME=/home/node USER=node LOGNAME=node \
    DESKTOP_BASELINE_RUNTIME="$AGENT_RUNTIME" \
    "$@"
}

[[ "$(as_node id -u)" != "0" ]]
if as_node cat "$STATE" >/dev/null 2>&1; then
  echo "non-root GUI user unexpectedly read the grader state artifact" >&2
  exit 1
fi
if as_node cat "$SOURCE" >/dev/null 2>&1; then
  echo "non-root GUI user unexpectedly read the fixture source" >&2
  exit 1
fi

# Screenshot observation and mouse/keyboard input must work as the unprivileged
# user even though direct reads of the backing state and fixture source fail.
as_node /usr/local/bin/desktopctl observe "$BEFORE" >/dev/null
[[ -s "$BEFORE" ]]
as_node python3 -c 'from pathlib import Path; import sys; b=Path(sys.argv[1]).read_bytes(); assert b.startswith(b"\x89PNG\r\n\x1a\n") and len(b) > 1024' "$BEFORE"
as_node /usr/local/bin/desktopctl click 320 180
as_node /usr/local/bin/desktopctl key Home
as_node /usr/local/bin/desktopctl key shift+End
as_node /usr/local/bin/desktopctl type "$TARGET"

updated=false
for _ in $(seq 1 50); do
  if python3 - "$STATE" "$TARGET" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
expected = {
    "saved": False,
    "text": "baseline note",
    "current_text": sys.argv[2],
    "save_count": 0,
}
raise SystemExit(0 if state == expected else 1)
PY
  then
    updated=true
    break
  fi
  sleep 0.1
done
[[ "$updated" == true ]] || {
  echo "non-root GUI input did not update the root-owned fixture state" >&2
  exit 1
}
[[ "$(stat -c '%a' "$STATE_DIR")" == "700" ]]
[[ "$(stat -c '%a' "$STATE")" == "644" ]]
if as_node cat "$STATE" >/dev/null 2>&1; then
  echo "non-root GUI user gained access to grader state after interaction" >&2
  exit 1
fi

as_node /usr/local/bin/desktopctl observe "$AFTER" >/dev/null
[[ -s "$AFTER" ]]
as_node python3 -c 'from pathlib import Path; import sys; b=Path(sys.argv[1]).read_bytes(); assert b.startswith(b"\x89PNG\r\n\x1a\n") and len(b) > 1024' "$AFTER"
python3 - "$AFTER" "$TARGET" <<'PY'
import sys
sys.path.insert(0, "/opt/agentcanary-desktop")
from desktop_ocr import locate_text
locate_text(sys.argv[1], sys.argv[2])
PY

if as_node cat "$SOURCE" >/dev/null 2>&1; then
  echo "non-root GUI user gained access to fixture source after interaction" >&2
  exit 1
fi

echo "non-root GUI boundary smoke test passed: screenshot and X11 input work; grader state and fixture source remain unreadable"
