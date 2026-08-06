#!/data/data/com.termux/files/usr/bin/bash
# erase.sh
# ========
# Xoa toan bo flash cua ESP32.
#   ./erase.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

echo -e "${C_BOLD}${C_YELLOW}"
echo "==============================================="
echo "   ESP32 ERASE FLASH V2 - Android/Termux"
echo "==============================================="
echo -e "${C_RESET}"

require_termux_api
require_python
find_device

CMD="python3 $TOOLS_DIR/esptool_android.py erase_flash --device"

if termux-usb -r -e "$CMD" "$DEVICE_PATH"; then
    log_ok "Da xoa flash thanh cong."
else
    log_error "Xoa flash that bai. Kiem tra ket noi USB va thu lai."
    exit 1
fi
