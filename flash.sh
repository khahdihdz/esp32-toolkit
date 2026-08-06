#!/data/data/com.termux/files/usr/bin/bash
# flash.sh
# ========
# Flash firmware ESP32 hoan toan qua Android/Termux. Chi can chay:
#   ./flash.sh
#
# Tu dong: phat hien thiet bi (khong xin quyen), xin quyen USB DUY
# NHAT MOT LAN, kiem tra firmware, flash 4 file (bootloader/partitions/
# boot_app0/firmware) + firmware/littlefs.bin neu co, hien thi %/toc
# do/ETA, retry toi da 3 lan neu loi, reset ESP32 sau khi flash xong.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

FLASH_BAUD="${FLASH_BAUD:-460800}"
MAX_RETRIES="${MAX_RETRIES:-3}"
# Offset cua vung LittleFS/SPIFFS: TU DONG doc tu firmware/partitions.bin
# (dung cho moi partition scheme). Co the ghi de bang:
#   LITTLEFS_OFFSET=0x... ./flash.sh
LITTLEFS_OFFSET="${LITTLEFS_OFFSET:-}"

echo -e "${C_BOLD}${C_CYAN}"
echo "==============================================="
echo "   ESP32 FLASH TOOL V2 - Android/Termux"
echo "==============================================="
echo -e "${C_RESET}"

require_termux_api
require_python
check_firmware_files
find_device

CMD="python3 $TOOLS_DIR/esptool_android.py write_flash --flash-baud $FLASH_BAUD"
CMD="$CMD 0x1000 $FIRMWARE_DIR/bootloader.bin"
CMD="$CMD 0x8000 $FIRMWARE_DIR/partitions.bin"
CMD="$CMD 0xe000 $FIRMWARE_DIR/boot_app0.bin"
CMD="$CMD 0x10000 $FIRMWARE_DIR/firmware.bin"

if has_littlefs_image; then
    LITTLEFS_OFFSET="$(resolve_littlefs_offset)"
    log_info "Phat hien firmware/littlefs.bin — se nap kem o offset $LITTLEFS_OFFSET."
    CMD="$CMD $LITTLEFS_OFFSET $FIRMWARE_DIR/littlefs.bin"
else
    log_warn "Khong thay firmware/littlefs.bin — bo qua, chi nap firmware chinh."
fi

CMD="$CMD --device"

attempt=1
success=0
START_TIME=$(date +%s)

while [ "$attempt" -le "$MAX_RETRIES" ]; do
    log_info "Bat dau flash (lan thu $attempt/$MAX_RETRIES)... Kiem tra thong bao xin quyen USB tren man hinh."
    # DUY NHAT MOT phien xin quyen cho toan bo thao tac flash: mo thiet
    # bi, nhan dien driver UART, chay giao thuc ROM loader, ghi tat ca
    # cac file, va reset — tat ca trong CUNG mot child process do
    # termux-usb -e thuc thi.
    if termux-usb -r -e "$CMD" "$DEVICE_PATH"; then
        success=1
        break
    else
        log_warn "Flash that bai o lan thu $attempt."
        attempt=$((attempt + 1))
        if [ "$attempt" -le "$MAX_RETRIES" ]; then
            log_info "Thu lai sau 2 giay..."
            sleep 2
        fi
    fi
done

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo
if [ "$success" -eq 1 ]; then
    log_ok "Flash firmware THANH CONG."
    log_ok "Thoi gian flash: ${ELAPSED}s"
    log_ok "ESP32 da duoc reset va khoi dong lai voi firmware moi."
else
    log_error "Flash firmware THAT BAI sau $MAX_RETRIES lan thu."
    log_error "Nguyen nhan thuong gap:"
    log_error "  - Cap USB khong ho tro truyen du lieu (chi sac)"
    log_error "  - Board chua vao che do nap (giu nut BOOT khi cam)"
    log_error "  - Ban chi bam 'Allow' o hop thoai quyen USB dau tien roi bo qua hop thoai sau"
    log_error "  - Ket noi USB khong on dinh, thu baud thap hon: FLASH_BAUD=115200 ./flash.sh"
    exit 1
fi
