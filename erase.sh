#!/data/data/com.termux/files/usr/bin/bash
# erase.sh
# ========
# Xóa toàn bộ flash của ESP32.
#   ./erase.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

echo -e "${C_BOLD}${C_YELLOW}"
echo "═══════════════════════════════════════════"
echo "   ESP32 ERASE FLASH - Android/Termux"
echo "═══════════════════════════════════════════"
echo -e "${C_RESET}"

require_termux_api
require_python
find_device

CMD="python3 \"$TOOLS_DIR/android_esptool.py\" erase_flash --device"

if termux-usb -r -e "$CMD" "$DEVICE_PATH"; then
    log_ok "Đã xóa flash thành công."
else
    log_error "Xóa flash thất bại. Kiểm tra kết nối USB và thử lại."
    exit 1
fi
