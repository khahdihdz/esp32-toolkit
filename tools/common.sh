#!/data/data/com.termux/files/usr/bin/bash
# common.sh
# =========
# Thư viện bash dùng chung cho toàn bộ script cấp cao (flash.sh,
# erase.sh, chipinfo.sh, mac.sh, monitor.sh, install.sh, doctor.sh,
# update.sh).

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
CONFIG_DIR="$ROOT_DIR/config"

require_termux_api() {
    if ! command -v termux-usb >/dev/null 2>&1; then
        log_error "Khong tim thay lenh 'termux-usb'."
        log_error "Chay: pkg install termux-api"
        log_error "Va cai ung dung 'Termux:API' tu F-Droid hoac Google Play."
        exit 1
    fi
}

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Khong tim thay python3. Chay: pkg install python"
        exit 1
    fi
}

# Chỉ liệt kê đường dẫn thiết bị (KHÔNG xin quyền, KHÔNG mở fd) rồi
# gán vào biến toàn cục DEVICE_PATH. Việc xin quyền thật sự (termux-usb
# -r -e) chỉ diễn ra MỘT LẦN, ngay tại lệnh thao tác thật sự (xem
# flash.sh/erase.sh/...), không phải ở đây. Đây là điểm khác biệt cố
# ý so với V1 để tránh lỗi "Permission denied" do xin quyền 2 lần.
find_device() {
    require_termux_api
    require_python
    log_info "Dang do tim thiet bi USB dang cam (khong can quyen)..."
    DEVICE_PATH="$(python3 "$TOOLS_DIR/usb_detect.py")"
    if [ -z "$DEVICE_PATH" ]; then
        log_error "Khong chon duoc thiet bi."
        exit 1
    fi
    log_ok "Da chon thiet bi: $DEVICE_PATH (se xin quyen Android trong buoc tiep theo)"
}

check_firmware_files() {
    local missing=0
    for f in bootloader.bin partitions.bin boot_app0.bin firmware.bin; do
        if [ ! -f "$FIRMWARE_DIR/$f" ]; then
            log_error "Thieu file firmware: firmware/$f"
            missing=1
        fi
    done
    if [ "$missing" -eq 1 ]; then
        log_error "Vui long dat day du file firmware vao thu muc firmware/ truoc khi flash."
        exit 1
    fi
}

has_littlefs_image() {
    [ -f "$FIRMWARE_DIR/littlefs.bin" ]
}

# Tu dong tim offset THAT SU cua vung LittleFS/SPIFFS bang cach doc
# truc tiep firmware/partitions.bin (chinh xac cho MOI partition
# scheme, khong con phai doan). Neu nguoi dung tu dat bien moi truong
# LITTLEFS_OFFSET thi uu tien dung gia tri do (bo qua tu dong do).
# Neu khong doc duoc / khong tim thay, fallback ve 0x290000 (offset
# cua default.csv) va canh bao ro rang day chi la doan.
resolve_littlefs_offset() {
    if [ -n "$LITTLEFS_OFFSET" ]; then
        log_info "Dung LITTLEFS_OFFSET nguoi dung tu dat: $LITTLEFS_OFFSET"
        echo "$LITTLEFS_OFFSET"
        return
    fi

    if [ -f "$FIRMWARE_DIR/partitions.bin" ]; then
        local detected
        detected="$(python3 "$TOOLS_DIR/partition_table.py" "$FIRMWARE_DIR/partitions.bin" --littlefs-offset-only 2>/dev/null)"
        if [ -n "$detected" ]; then
            log_ok "Tu dong phat hien offset LittleFS tu partitions.bin: $detected"
            echo "$detected"
            return
        fi
        log_warn "Khong doc duoc offset LittleFS tu partitions.bin, dung gia tri doan 0x290000."
    else
        log_warn "Khong thay firmware/partitions.bin de tu dong do offset, dung gia tri doan 0x290000."
    fi
    echo "0x290000"
}
