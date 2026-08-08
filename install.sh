#!/data/data/com.termux/files/usr/bin/bash
# install.sh
# ==========
# Cai dat toan bo dependency can thiet de chay ESP32 Android Toolkit V2
# tren Termux (Android 10-16), khong can PlatformIO, khong can may tinh,
# khong can root, khong can adb.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

log_info "Bat dau cai dat ESP32 Android Toolkit V2 cho Termux..."
echo

log_info "Cap nhat danh sach goi..."
pkg update -y
pkg upgrade -y

log_info "Cai dat cac goi he thong can thiet..."
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

log_ok "Da cai xong cac goi he thong."
echo

log_info "Nang cap pip..."
python3 -m pip install --upgrade pip

log_info "Cai dat thu vien Python (libusb1)..."
python3 -m pip install --upgrade libusb1 --break-system-packages || \
    python3 -m pip install --upgrade libusb1

log_ok "Da cai xong thu vien Python."
echo

log_info "Kiem tra moi truong sau khi cai dat..."

check_ok=1

if command -v python3 >/dev/null 2>&1; then
    PY_VERSION="$(python3 --version 2>&1)"
    log_ok "Python: $PY_VERSION"
else
    log_error "Python chua duoc cai dat dung cach."
    check_ok=0
fi

if command -v termux-usb >/dev/null 2>&1; then
    log_ok "termux-usb: da san sang"
else
    log_error "termux-usb chua san sang. Cai ung dung Termux:API tu F-Droid/Google Play."
    check_ok=0
fi

if python3 -c "import usb1" >/dev/null 2>&1; then
    log_ok "Thu vien Python 'libusb1': da san sang"
else
    log_error "Thu vien Python 'libusb1' chua cai duoc. Thu lai: pip install libusb1 --break-system-packages"
    check_ok=0
fi

if python3 -c "
import sys
sys.path.insert(0, '$TOOLS_DIR')
import android_usb  # noqa: F401
import usb1
usb1.USBContext().close()
" >/dev/null 2>&1; then
    log_ok "Thu vien native libusb-1.0.so: nap thanh cong."
else
    log_error "Khong nap duoc libusb-1.0.so. Kiem tra: ls \$PREFIX/lib/libusb-1.0.so*"
    check_ok=0
fi

if [ -f "$FIRMWARE_DIR/firmware.bin" ]; then
    log_ok "Da tim thay firmware trong thu muc firmware/"
else
    log_warn "Chua co firmware trong thu muc firmware/. Ban can build hoac copy firmware vao do truoc khi flash."
fi

if [ -f "$CONFIG_DIR/config.json" ] && [ -f "$CONFIG_DIR/partition.json" ]; then
    log_ok "File cau hinh config/config.json va config/partition.json: da san sang"
else
    log_warn "Thieu file cau hinh trong config/. Toolkit se dung gia tri mac dinh trong code."
fi

echo
if [ "$check_ok" -eq 1 ]; then
    log_ok "Cai dat hoan tat! Chay './doctor.sh' de kiem tra chi tiet moi truong."
    log_ok "Sau do chay './flash.sh' de nap firmware."
else
    log_error "Cai dat gap mot so van de, xem chi tiet o tren."
    exit 1
fi
