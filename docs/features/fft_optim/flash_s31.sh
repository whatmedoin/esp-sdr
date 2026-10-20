#!/usr/bin/env bash
# Flash an S31 image while the board is already in download mode.
# This script deliberately does not perform a hard reset or USB-level reset.
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
IMAGE_DIR="${IMAGE_DIR:-$ROOT/build-s31-local}"
IDF_PATH="${IDF_PATH:-$HOME/esp-sdr-tooling/esp-idf}"
IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$HOME/esp-sdr-tooling/espressif}"

export PATH="$HOME/.pyenv/versions/3.12.13/bin:$PATH"
export IDF_TOOLS_PATH
. "$IDF_PATH/export.sh"

if [ ! -f "$IMAGE_DIR/esp_sdr.bin" ]; then
  echo "missing $IMAGE_DIR/esp_sdr.bin; build first" >&2
  exit 1
fi

echo "The board must already be in download mode."
echo "If it is not, hold BOOT, tap RESET, then reconnect it."

python -m esptool --chip esp32s31 -p "$PORT" -b 460800 \
  --before no-reset --after no-reset --no-stub write-flash \
  --flash-mode dio --flash-size 2MB --flash-freq 80m \
  0x2000 "$IMAGE_DIR/bootloader/bootloader.bin" \
  0x8000 "$IMAGE_DIR/partition_table/partition-table.bin" \
  0x10000 "$IMAGE_DIR/esp_sdr.bin"

python -m esptool --chip esp32s31 -p "$PORT" \
  --before no-reset --after watchdog-reset run

echo
echo "Watchdog reset re-enumerates the USB port; rescan /dev/ttyACM*."
