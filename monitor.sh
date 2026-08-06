#!/data/data/com.termux/files/usr/bin/bash
# monitor.sh
# ==========
# Serial Monitor cho ESP32.
#   ./monitor.sh                       # baud mac dinh 115200
#   BAUD=921600 ./monitor.sh           # doi baud (115200/230400/460800/921600)
#   LOG_FILE=session.log ./monitor.sh  # luu log ra file
#   FILTER='ERROR' ./monitor.sh        # chi hien dong khop regex
#
# Nhan Ctrl+C de thoat.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

BAUD="${BAUD:-115200}"

require_termux_api
require_python
find_device

# Luu y: termux-usb -e khong chay qua shell nen khong ho tro dau ngoac
# kep bao quanh tham so — LOG_FILE/FILTER co khoang trang se bi tach
# thanh nhieu tham so. Dung duong dan/regex khong chua khoang trang.
CMD="python3 $TOOLS_DIR/serial_monitor.py --baud $BAUD"
if [ -n "$LOG_FILE" ]; then
    CMD="$CMD --log $LOG_FILE"
fi
if [ -n "$FILTER" ]; then
    CMD="$CMD --filter $FILTER"
fi
if [ -n "$NO_RESET" ]; then
    CMD="$CMD --no-reset"
fi

# serial_monitor.py nhan duong dan thiet bi lam THAM SO VI TRI cuoi
# cung (khong phai --device), vi termux-usb tu them no vao cuoi dong
# lenh -e.
termux-usb -r -e "$CMD" "$DEVICE_PATH"
