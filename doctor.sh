#!/data/data/com.termux/files/usr/bin/bash
# doctor.sh
# =========
# Kiểm tra toàn diện môi trường trước khi flash ESP32: Python, Android
# version, USB Host, OTG, Termux API, firmware, quyền USB, phát hiện
# ESP32 đang cắm.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"
set +e  # doctor.sh không nên dừng giữa chừng khi 1 mục kiểm tra lỗi

PASS=0
FAIL=0
WARN=0

check_pass() { log_ok "$1"; PASS=$((PASS + 1)); }
check_fail() { log_error "$1"; FAIL=$((FAIL + 1)); }
check_warn() { log_warn "$1"; WARN=$((WARN + 1)); }

echo -e "${C_BOLD}${C_CYAN}"
echo "═══════════════════════════════════════════"
echo "   ESP32 ANDROID TOOLKIT - DOCTOR"
echo "═══════════════════════════════════════════"
echo -e "${C_RESET}"

# 1. Python version
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 --version 2>&1 | awk '{print $2}')"
    check_pass "Python: $PY_VER"
else
    check_fail "Python chưa được cài đặt. Chạy: pkg install python"
fi

# 2. Android version
if command -v getprop >/dev/null 2>&1; then
    ANDROID_VER="$(getprop ro.build.version.release 2>/dev/null)"
    if [ -n "$ANDROID_VER" ]; then
        check_pass "Android version: $ANDROID_VER"
    else
        check_warn "Không đọc được Android version (getprop không trả về giá trị)."
    fi
else
    check_warn "Không tìm thấy 'getprop', bỏ qua kiểm tra Android version."
fi

# 3. USB Host / OTG support
if [ -d /sys/bus/usb ] || command -v lsusb >/dev/null 2>&1; then
    check_pass "Thiết bị có hỗ trợ USB Host (subsystem /sys/bus/usb tồn tại)."
else
    check_warn "Không xác nhận được USB Host. Một số thiết bị không hỗ trợ OTG."
fi

# 4. Termux:API
if command -v termux-usb >/dev/null 2>&1; then
    check_pass "termux-api (termux-usb): đã cài."
    if timeout 5 termux-usb -l >/dev/null 2>&1; then
        check_pass "termux-usb phản hồi bình thường."
    else
        check_warn "termux-usb không phản hồi. Kiểm tra ứng dụng Termux:API đã cài và cấp quyền chưa."
    fi
else
    check_fail "termux-usb chưa cài. Chạy: pkg install termux-api và cài app Termux:API."
fi

# 5. Thư viện Python libusb1
if python3 -c "import usb1" >/dev/null 2>&1; then
    check_pass "Thư viện Python 'libusb1': đã cài."
else
    check_fail "Thiếu thư viện Python 'libusb1'. Chạy: pip install libusb1"
fi

# 6. Firmware
missing_fw=0
for f in bootloader.bin partitions.bin boot_app0.bin firmware.bin; do
    if [ -f "$FIRMWARE_DIR/$f" ]; then
        check_pass "Firmware: $f có sẵn."
    else
        check_warn "Firmware: thiếu $f trong thư mục firmware/."
        missing_fw=1
    fi
done

# 7. Quyền truy cập USB hiện tại + phát hiện ESP32
log_info "Đang dò tìm thiết bị USB đang cắm..."
DEVICES_JSON="$(timeout 5 termux-usb -l 2>/dev/null)"
if [ -n "$DEVICES_JSON" ] && [ "$DEVICES_JSON" != "[]" ]; then
    check_pass "Phát hiện thiết bị USB đang cắm: $DEVICES_JSON"
    log_info "Chạy './chipinfo.sh' để xác nhận đây có phải ESP32 hay không."
else
    check_warn "Không phát hiện thiết bị USB nào. Cắm cáp OTG + board ESP32 rồi chạy lại doctor.sh."
fi

echo
echo -e "${C_BOLD}═══════════════════════════════════════════${C_RESET}"
echo -e "Kết quả: ${C_GREEN}${PASS} PASS${C_RESET}  ${C_YELLOW}${WARN} WARNING${C_RESET}  ${C_RED}${FAIL} FAIL${C_RESET}"
echo -e "${C_BOLD}═══════════════════════════════════════════${C_RESET}"

if [ "$FAIL" -gt 0 ]; then
    log_error "Vui lòng khắc phục các mục FAIL ở trên trước khi flash."
    exit 1
elif [ "$WARN" -gt 0 ]; then
    log_warn "Có một số cảnh báo, nhưng có thể vẫn flash được. Kiểm tra lại nếu gặp lỗi."
    exit 0
else
    log_ok "Môi trường sẵn sàng! Chạy './flash.sh' để bắt đầu."
    exit 0
fi
