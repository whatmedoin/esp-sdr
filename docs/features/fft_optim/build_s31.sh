#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
IDF_PATH="${IDF_PATH:-$HOME/esp-sdr-tooling/esp-idf}"
IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$HOME/esp-sdr-tooling/espressif}"
BUILD_DIR="${BUILD_DIR:-build-s31-local}"

export PATH="$HOME/.pyenv/versions/3.12.13/bin:$PATH"
export IDF_TOOLS_PATH
. "$IDF_PATH/export.sh"

cd "$ROOT"
idf.py --preview -B "$BUILD_DIR" \
  -DIDF_TARGET=esp32s31 \
  -DSDKCONFIG="$BUILD_DIR/sdkconfig" \
  -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32s31 "$@" build

echo
echo "Built: $ROOT/$BUILD_DIR/esp_sdr.bin"
