#!/data/data/com.termux/files/usr/bin/bash
# verify.sh
# =========
# So sanh MD5 cua tung file firmware da flash voi file .bin goc, de
# xac dinh flash co thuc su toan ven hay khong (loai tru kha nang
# flash bi loi am tham ma flash.sh khong phat hien ra).
#   ./verify.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

LITTLEFS_OFFSET="${LITTLEFS_OFFSET:-}"

require_termux_api
require_python
check_firmware_files
find_device

CMD="python3 $TOOLS_DIR/esptool_android.py verify_flash"
CMD="$CMD 0x1000 $FIRMWARE_DIR/bootloader.bin"
CMD="$CMD 0x8000 $FIRMWARE_DIR/partitions.bin"
CMD="$CMD 0xe000 $FIRMWARE_DIR/boot_app0.bin"
CMD="$CMD 0x10000 $FIRMWARE_DIR/firmware.bin"

if has_littlefs_image; then
    LITTLEFS_OFFSET="$(resolve_littlefs_offset)"
    CMD="$CMD $LITTLEFS_OFFSET $FIRMWARE_DIR/littlefs.bin"
fi

CMD="$CMD --device"

termux-usb -r -e "$CMD" "$DEVICE_PATH"
