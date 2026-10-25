#!/usr/bin/env bash
set -euo pipefail

# The local model is enabled only in the dedicated deterministic integration image.
# Normal baseline and reference-controller images do not contain the sentinel.
if [[ -f /opt/agentcanary-desktop/enable-model-stub ]]; then
    nohup python3 /opt/agentcanary-desktop/desktop_model_stub.py \
        >/tmp/agentcanary-desktop-model-stub.log 2>&1 </dev/null &
    ready=false
    for _ in $(seq 1 40); do
        if curl -fsS http://127.0.0.1:8765/health >/dev/null; then
            ready=true
            break
        fi
        sleep 0.25
    done
    if [[ "$ready" != true ]]; then
        echo "desktop model stub did not become ready" >&2
        cat /tmp/agentcanary-desktop-model-stub.log >&2 || true
        exit 1
    fi
fi

exec /opt/mock-api/entrypoint.sh "$@"
