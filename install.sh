#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Thư mục repo = thư mục chứa script này (không hard-code đường dẫn tuyệt đối).
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
PYTHON="${PYTHON:-$PREFIX/bin/python}"

chmod +x "$BASE/run_worker.sh" "$BASE/start.sh" 2>/dev/null || true
mkdir -p "$BASE/logs"

echo "[OK] Đã cài ESP32 USB Flasher v3."
echo "Chạy menu:"
echo "  $PYTHON $BASE/esp32_usb_flasher.py --menu"
echo "Hoặc:"
echo "  $BASE/start.sh"
