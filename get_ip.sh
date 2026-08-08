#!/data/data/com.termux/files/usr/bin/bash
# get_ip.sh
# =========
# Reset ESP32 va doc dia chi IP ma firmware in ra qua Serial khi ket
# noi WiFi (che do tram hoac AP), roi thoat - khong can mo Serial
# Monitor thu cong.
#   ./get_ip.sh
#   BAUD=921600 ./get_ip.sh      # doi baud
#   TIMEOUT=30 ./get_ip.sh       # doi thoi gian cho toi da (giay)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

BAUD="${BAUD:-115200}"
TIMEOUT="${TIMEOUT:-20}"

require_termux_api
require_python
find_device

CMD="python3 $TOOLS_DIR/get_ip.py --baud $BAUD --timeout $TIMEOUT"
if [ -n "$NO_RESET" ]; then
    CMD="$CMD --no-reset"
fi

termux-usb -r -e "$CMD" "$DEVICE_PATH"
