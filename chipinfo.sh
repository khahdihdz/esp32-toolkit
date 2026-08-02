#!/data/data/com.termux/files/usr/bin/bash
# chipinfo.sh
# ===========
# Hiển thị thông tin chi tiết chip ESP32 đang cắm.
#   ./chipinfo.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

require_termux_api
require_python
find_device

CMD="python3 \"$TOOLS_DIR/chipinfo.py\" --device"
termux-usb -r -e "$CMD" "$DEVICE_PATH"
