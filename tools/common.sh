#!/data/data/com.termux/files/usr/bin/bash
# common.sh
# =========
# Thư viện bash dùng chung cho toàn bộ script cấp cao (flash.sh,
# erase.sh, chipinfo.sh, mac.sh, monitor.sh, install.sh, doctor.sh,
# update.sh). Tuân thủ POSIX một cách hợp lý, nhưng dùng bash vì
# Termux mặc định có bash.

# Không set -u để tránh lỗi với các biến môi trường Termux đặc thù,
# nhưng vẫn dừng ngay khi có lệnh lỗi.
set -e

# ANSI colors
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_RED='\033[31m'
C_GREEN='\033[32m'
C_YELLOW='\033[33m'
C_CYAN='\033[36m'
C_DIM='\033[2m'

log_info()  { echo -e "${C_CYAN}${C_BOLD}[INFO]${C_RESET} $*"; }
log_ok()    { echo -e "${C_GREEN}${C_BOLD}[OK]${C_RESET} $*"; }
log_warn()  { echo -e "${C_YELLOW}${C_BOLD}[WARNING]${C_RESET} $*"; }
log_error() { echo -e "${C_RED}${C_BOLD}[ERROR]${C_RESET} $*" 1>&2; }

# Xác định thư mục gốc của dự án (nơi chứa flash.sh, tools/, firmware/).
project_root() {
    local src="${BASH_SOURCE[0]}"
    cd "$(dirname "$src")/.." && pwd
}

ROOT_DIR="$(project_root)"
TOOLS_DIR="$ROOT_DIR/tools"
FIRMWARE_DIR="$ROOT_DIR/firmware"

require_termux_api() {
    if ! command -v termux-usb >/dev/null 2>&1; then
        log_error "Không tìm thấy lệnh 'termux-usb'."
        log_error "Chạy: pkg install termux-api"
        log_error "Và cài ứng dụng 'Termux:API' từ F-Droid hoặc Google Play."
        exit 1
    fi
}

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Không tìm thấy python3. Chạy: pkg install python"
        exit 1
    fi
}

# Tìm đường dẫn thiết bị ESP32, hỗ trợ chọn nếu có nhiều thiết bị.
# Kết quả được in ra bằng python (usb_helper) và gán vào biến toàn cục
# DEVICE_PATH.
find_device() {
    require_termux_api
    require_python
    log_info "Đang dò tìm thiết bị ESP32 qua USB..."
    DEVICE_PATH="$(python3 "$TOOLS_DIR/select_device.py")"
    if [ -z "$DEVICE_PATH" ]; then
        log_error "Không chọn được thiết bị."
        exit 1
    fi
    log_ok "Đã chọn thiết bị: $DEVICE_PATH"
}

check_firmware_files() {
    local missing=0
    for f in bootloader.bin partitions.bin boot_app0.bin firmware.bin; do
        if [ ! -f "$FIRMWARE_DIR/$f" ]; then
            log_error "Thiếu file firmware: firmware/$f"
            missing=1
        fi
    done
    if [ "$missing" -eq 1 ]; then
        log_error "Vui lòng đặt đầy đủ file firmware vào thư mục firmware/ trước khi flash."
        exit 1
    fi
}
