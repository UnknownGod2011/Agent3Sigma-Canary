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
if grep -Eq 'your-api-key-here|sk-your-key-here|sk-ant-your-key-here|api\\.example\\.com' workflow/images/official/openclaw.json; then
  echo "error: generated OpenClaw config still contains example credentials/endpoints" >&2
  exit 2
fi

# prepare.sh expects the same isolated build-context contract used by the
# credential-free smoke workflow. Keep the generated provider config in that
# ephemeral context; never write credentials into the source tree beyond the
# already-ignored/generated AgentCanary config files.
BUILD_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

bash workflow/images/desktop_baseline/prepare.sh "$BUILD_DIR" "" "$ROOT"
docker build -t agentcanary-desktop-baseline "$BUILD_DIR"

export DOCKER_IMAGE=agentcanary-desktop-baseline
RESULTS_DIR="${AGENTCANARY_DESKTOP_RESULTS:-results/desktop-baseline}"

uv run python scripts/benchmark.py \
  --model "$MODEL" \
  --suite task_9000_desktop_notes_gui \
  --docker \
  --output-dir "$RESULTS_DIR" \
  --verbose

# A zero benchmark process exit is not, by itself, evidence that the research
# milestone succeeded. Require the persisted AgentCanary result to contain the
# fail-closed 1.0 grade and a genuine desktop observation/action trajectory.
uv run python workflow/images/desktop_baseline/verify_benchmark.py "$RESULTS_DIR"
