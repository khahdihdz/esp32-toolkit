#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"

exec "${PYTHON:-$PREFIX/bin/python}" "$BASE/esp32_usb_flasher.py" --menu
