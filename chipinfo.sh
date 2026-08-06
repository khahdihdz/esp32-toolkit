#!/data/data/com.termux/files/usr/bin/bash
# chipinfo.sh
# ===========
# Hien thi thong tin chi tiet chip ESP32 dang cam (chip, MAC, magic
# register).
#   ./chipinfo.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

require_termux_api
require_python
find_device

CMD="python3 $TOOLS_DIR/esptool_android.py chip_id --device"
termux-usb -r -e "$CMD" "$DEVICE_PATH"
