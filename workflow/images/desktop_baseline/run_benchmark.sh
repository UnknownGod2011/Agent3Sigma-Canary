#!/usr/bin/env bash
set -euo pipefail

# Run the desktop baseline through AgentCanary's real benchmark lifecycle.
# This intentionally refuses to invent or persist model credentials. Run
# `bash setup.sh` first with a real provider configured in config.yaml.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

MODEL="${1:-${AGENTCANARY_DESKTOP_MODEL:-}}"
if [[ -z "$MODEL" ]]; then
  echo "error: provide a configured model as argument 1 or AGENTCANARY_DESKTOP_MODEL" >&2
  exit 2
fi

if [[ ! -f env.sh || ! -f workflow/images/official/openclaw.json ]]; then
  echo "error: generated env.sh/openclaw.json missing; configure config.yaml and run: bash setup.sh" >&2
  exit 2
fi

# shellcheck disable=SC1091
source env.sh

# Reject the example/placeholder configuration rather than accidentally
# reporting a benchmark attempt that never had a usable evaluated model.
if grep -Eq 'your-api-key-here|sk-your-key-here|sk-ant-your-key-here|api\.example\.com' workflow/images/official/openclaw.json; then
  echo "error: generated OpenClaw config still contains example credentials/endpoints" >&2
  exit 2
fi

bash workflow/images/desktop_baseline/prepare.sh
docker build -t agentcanary-desktop-baseline workflow/images/desktop_baseline/docker

export DOCKER_IMAGE=agentcanary-desktop-baseline
exec uv run python scripts/benchmark.py \
  --model "$MODEL" \
  --suite task_9000_desktop_notes_gui \
  --docker \
  --output-dir "${AGENTCANARY_DESKTOP_RESULTS:-results/desktop-baseline}" \
  --verbose
