#!/data/data/com.termux/files/usr/bin/bash
# install.sh
# ==========
# Cài đặt toàn bộ dependency cần thiết để chạy bộ công cụ ESP32 trên
# Termux (Android 10-15), không cần PlatformIO, không cần máy tính.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

log_info "Bắt đầu cài đặt bộ công cụ ESP32 cho Termux..."
echo

log_info "Cập nhật danh sách gói..."
pkg update -y
pkg upgrade -y

log_info "Cài đặt các gói hệ thống cần thiết..."
pkg install -y \
    git \
    python \
    clang \
    make \
    cmake \
    termux-api \
    jq \
    unzip \
    wget \
    curl \
    coreutils \
    usbutils \
    libusb \
    binutils

log_ok "Đã cài xong các gói hệ thống."
echo

log_info "Nâng cấp pip..."
python3 -m pip install --upgrade pip

log_info "Cài đặt thư viện Python (libusb1)..."
python3 -m pip install --upgrade libusb1

log_ok "Đã cài xong thư viện Python."
echo

log_info "Kiểm tra môi trường sau khi cài đặt..."

check_ok=1

if command -v python3 >/dev/null 2>&1; then
    PY_VERSION="$(python3 --version 2>&1)"
    log_ok "Python: $PY_VERSION"
else
    log_error "Python chưa được cài đặt đúng cách."
    check_ok=0
fi

if command -v termux-usb >/dev/null 2>&1; then
    log_ok "termux-usb: đã sẵn sàng"
else
    log_error "termux-usb chưa sẵn sàng. Cài ứng dụng Termux:API từ F-Droid/Google Play."
    check_ok=0
fi

if python3 -c "import usb1" >/dev/null 2>&1; then
    log_ok "Thư viện libusb1 (Python): đã sẵn sàng"
else
    log_error "Thư viện libusb1 (Python) chưa cài được. Thử lại: pip install libusb1"
    check_ok=0
fi

if [ -f "$FIRMWARE_DIR/firmware.bin" ]; then
    log_ok "Đã tìm thấy firmware trong thư mục firmware/"
else
    log_warn "Chưa có firmware trong thư mục firmware/. Bạn cần build hoặc copy firmware vào đó trước khi flash."
fi

echo
if [ "$check_ok" -eq 1 ]; then
    log_ok "Cài đặt hoàn tất! Chạy './doctor.sh' để kiểm tra chi tiết môi trường."
    log_ok "Sau đó chạy './flash.sh' để nạp firmware."
else
    log_error "Cài đặt gặp một số vấn đề, xem chi tiết ở trên."
    exit 1
fi
