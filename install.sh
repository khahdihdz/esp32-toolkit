#!/data/data/com.termux/files/usr/bin/bash
set -e
BASE="/data/data/com.termux/files/home/esp32-toolkit"
chmod +x "$BASE/run_worker.sh"
mkdir -p "$BASE/logs"
echo "[OK] Đã cài ESP32 USB Flasher v3."
echo "Chạy menu:"
echo "  python $BASE/esp32_usb_flasher.py --menu"
echo "Hoặc:"
echo "  $BASE/start.sh"
