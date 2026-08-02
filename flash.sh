#!/data/data/com.termux/files/usr/bin/bash
# flash.sh
# ========
# Flash firmware ESP32 hoàn toàn qua Android/Termux. Chỉ cần chạy:
#   ./flash.sh
#
# Tự động: phát hiện thiết bị, xin quyền USB, kiểm tra firmware, flash
# 4 file (bootloader/partitions/boot_app0/firmware) + firmware/littlefs.bin
# nếu có (dashboard web, filesystem...), hiển thị %, tốc độ, ETA, retry
# tối đa 3 lần nếu lỗi, reset ESP32 sau khi flash xong.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

FLASH_BAUD="${FLASH_BAUD:-460800}"
MAX_RETRIES=3
# Offset mặc định của partition "spiffs" trong min_spiffs.csv (arduino-esp32).
# Nếu project của bạn dùng partition scheme khác (default.csv, default_8MB.csv...)
# thì offset LittleFS sẽ khác — ghi đè bằng biến môi trường LITTLEFS_OFFSET,
# ví dụ: LITTLEFS_OFFSET=0x290000 ./flash.sh
LITTLEFS_OFFSET="${LITTLEFS_OFFSET:-0x3D0000}"

echo -e "${C_BOLD}${C_CYAN}"
echo "═══════════════════════════════════════════"
echo "   ESP32 FLASH TOOL - Android/Termux"
echo "═══════════════════════════════════════════"
echo -e "${C_RESET}"

require_termux_api
require_python
check_firmware_files
find_device

CMD="python3 $TOOLS_DIR/android_esptool.py write_flash --flash-baud $FLASH_BAUD"
CMD="$CMD 0x1000 $FIRMWARE_DIR/bootloader.bin"
CMD="$CMD 0x8000 $FIRMWARE_DIR/partitions.bin"
CMD="$CMD 0xe000 $FIRMWARE_DIR/boot_app0.bin"
CMD="$CMD 0x10000 $FIRMWARE_DIR/firmware.bin"

if has_littlefs_image; then
    log_info "Phát hiện firmware/littlefs.bin — sẽ nạp kèm ở offset $LITTLEFS_OFFSET."
    CMD="$CMD $LITTLEFS_OFFSET $FIRMWARE_DIR/littlefs.bin"
else
    log_warn "Không thấy firmware/littlefs.bin — bỏ qua, chỉ nạp firmware chính."
fi

CMD="$CMD --device"

attempt=1
success=0
START_TIME=$(date +%s)

while [ "$attempt" -le "$MAX_RETRIES" ]; do
    log_info "Bắt đầu flash (lần thử $attempt/$MAX_RETRIES)..."
    if termux-usb -r -e "$CMD" "$DEVICE_PATH"; then
        success=1
        break
    else
        log_warn "Flash thất bại ở lần thử $attempt."
        attempt=$((attempt + 1))
        if [ "$attempt" -le "$MAX_RETRIES" ]; then
            log_info "Thử lại sau 2 giây..."
            sleep 2
        fi
    fi
done

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo
if [ "$success" -eq 1 ]; then
    log_ok "Flash firmware THÀNH CÔNG."
    log_ok "Thời gian flash: ${ELAPSED}s"
    log_ok "ESP32 đã được reset và khởi động lại với firmware mới."
else
    log_error "Flash firmware THẤT BẠI sau $MAX_RETRIES lần thử."
    log_error "Nguyên nhân thường gặp:"
    log_error "  - Cáp USB không hỗ trợ truyền dữ liệu (chỉ sạc)"
    log_error "  - Board chưa vào chế độ nạp (giữ nút BOOT khi cắm)"
    log_error "  - Kết nối USB không ổn định, thử baud thấp hơn: FLASH_BAUD=115200 ./flash.sh"
    exit 1
fi
