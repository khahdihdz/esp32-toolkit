#!/data/data/com.termux/files/usr/bin/bash
# monitor.sh
# ==========
# Serial Monitor cho ESP32.
#   ./monitor.sh                     # baud mặc định 115200
#   BAUD=921600 ./monitor.sh         # đổi baud
#   LOG_FILE=session.log ./monitor.sh  # lưu log ra file
#   FILTER='ERROR' ./monitor.sh      # chỉ hiện dòng khớp regex
#
# Nhấn Ctrl+C để thoát.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

BAUD="${BAUD:-115200}"

require_termux_api
require_python
find_device

# Lưu ý: termux-usb -e không chạy qua shell nên không hỗ trợ dấu ngoặc kép
# bao quanh tham số — LOG_FILE/FILTER có khoảng trắng sẽ bị tách thành
# nhiều tham số. Dùng đường dẫn/regex không chứa khoảng trắng.
CMD="python3 $TOOLS_DIR/serial_monitor.py --baud $BAUD"
if [ -n "$LOG_FILE" ]; then
    CMD="$CMD --log $LOG_FILE"
fi
if [ -n "$FILTER" ]; then
    CMD="$CMD --filter $FILTER"
fi

# Lưu ý: serial_monitor.py nhận đường dẫn thiết bị làm THAM SỐ VỊ TRÍ
# cuối cùng (không phải --device), vì termux-usb tự thêm nó vào cuối
# dòng lệnh -e.
termux-usb -r -e "$CMD" "$DEVICE_PATH"
