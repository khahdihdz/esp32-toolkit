#!/data/data/com.termux/files/usr/bin/bash
# mac.sh
# ======
# In dia chi MAC cua ESP32 dang cam.
#   ./mac.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

require_termux_api
require_python
find_device

CMD="python3 $TOOLS_DIR/esptool_android.py read_mac --device"
termux-usb -r -e "$CMD" "$DEVICE_PATH"
