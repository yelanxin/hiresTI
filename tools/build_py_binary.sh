#!/bin/bash
set -euo pipefail

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "Error: pyinstaller is required. Install with: pip3 install pyinstaller"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/build_tmp/pyi-dist}"
WORK_DIR="${2:-$ROOT_DIR/build_tmp/pyi-work}"
SPEC_DIR="${3:-$ROOT_DIR/build_tmp/pyi-spec}"

mkdir -p "$OUT_DIR" "$WORK_DIR" "$SPEC_DIR"
cd "$ROOT_DIR"

ADD_DATA_ARGS=(
  --add-data "icons:icons"
  --add-data "ui:ui"
  --add-data "actions:actions"
)

if [ -d "css" ]; then
  ADD_DATA_ARGS+=(--add-data "css:css")
fi
if [ -f "version.txt" ]; then
  ADD_DATA_ARGS+=(--add-data "version.txt:.")
fi

pyinstaller \
  --noconfirm \
  --clean \
  --name "hiresti_app" \
  --onedir \
  --distpath "$OUT_DIR" \
  --workpath "$WORK_DIR" \
  --specpath "$SPEC_DIR" \
  "${ADD_DATA_ARGS[@]}" \
  --collect-submodules gi \
  --collect-submodules cairo \
  --collect-all PIL \
  --collect-all pystray \
  --collect-all qrcode \
  main.py

echo "Built binary bundle at: $OUT_DIR/hiresti_app"
