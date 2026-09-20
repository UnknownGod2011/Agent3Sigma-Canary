#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="$1"
PROJECT_DIR="$3"
IMAGES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFICIAL_DIR="$(cd "${IMAGES_DIR}/../official" && pwd)"

if [[ -z "${BUILD_DIR}" ]]; then
    echo "[ERROR] BUILD_DIR is not specified" >&2
    exit 1
fi

# Reuse the official runner's task-agnostic OpenClaw/mock-api context so the
# experiment changes only the GUI capability surface.
bash "${OFFICIAL_DIR}/prepare.sh" "${BUILD_DIR}" "" "${PROJECT_DIR}"

cp "${IMAGES_DIR}/Dockerfile" "${BUILD_DIR}/Dockerfile"
cp "${IMAGES_DIR}/smoke_test.sh" "${BUILD_DIR}/smoke_test.sh"
mkdir -p "${BUILD_DIR}/desktop"
cp "${IMAGES_DIR}/desktop/notes_app.py" "${BUILD_DIR}/desktop/notes_app.py"
cp "${IMAGES_DIR}/desktop/desktopctl" "${BUILD_DIR}/desktop/desktopctl"

echo "[INFO] desktop_baseline build context prepared"
