#!/data/data/com.termux/files/usr/bin/bash
# doctor.sh
# =========
# Kiem tra toan dien moi truong truoc khi flash ESP32: Python, Android
# version, USB Host, OTG, Termux API, firmware, cau hinh, thiet bi
# USB dang cam (chi liet ke, KHONG xin quyen).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"
set +e  # doctor.sh khong nen dung giua chung khi 1 muc kiem tra loi

PASS=0
FAIL=0
WARN=0

check_pass() { log_ok "$1"; PASS=$((PASS + 1)); }
check_fail() { log_error "$1"; FAIL=$((FAIL + 1)); }
check_warn() { log_warn "$1"; WARN=$((WARN + 1)); }

echo -e "${C_BOLD}${C_CYAN}"
echo "==============================================="
echo "   ESP32 ANDROID TOOLKIT V2 - DOCTOR"
echo "==============================================="
echo -e "${C_RESET}"

# 1. Python version
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 --version 2>&1 | awk '{print $2}')"
    check_pass "Python: $PY_VER"
else
    check_fail "Python chua duoc cai dat. Chay: pkg install python"
fi

# 2. Android version
if command -v getprop >/dev/null 2>&1; then
    ANDROID_VER="$(getprop ro.build.version.release 2>/dev/null)"
    if [ -n "$ANDROID_VER" ]; then
        check_pass "Android version: $ANDROID_VER"
    else
        check_warn "Khong doc duoc Android version (getprop khong tra ve gia tri)."
    fi
else
    check_warn "Khong tim thay 'getprop', bo qua kiem tra Android version."
fi

# 3. USB Host / OTG support
if [ -d /sys/bus/usb ] || command -v lsusb >/dev/null 2>&1; then
    check_pass "Thiet bi co ho tro USB Host (subsystem /sys/bus/usb ton tai)."
else
    check_warn "Khong xac nhan duoc USB Host. Mot so thiet bi khong ho tro OTG."
fi

# 4. Termux:API
if command -v termux-usb >/dev/null 2>&1; then
    check_pass "termux-api (termux-usb): da cai."
    if timeout 5 termux-usb -l >/dev/null 2>&1; then
        check_pass "termux-usb phan hoi binh thuong."
    else
        check_warn "termux-usb khong phan hoi. Kiem tra ung dung Termux:API da cai va cap quyen chua."
    fi
else
    check_fail "termux-usb chua cai. Chay: pkg install termux-api va cai app Termux:API."
fi

# 5. Thư viện Python libusb1 + thư viện native libusb-1.0.so
if python3 -c "import usb1" >/dev/null 2>&1; then
    check_pass "Thu vien Python 'libusb1': da cai."
else
    check_fail "Thieu thu vien Python 'libusb1'. Chay: pip install libusb1 --break-system-packages"
fi

if python3 -c "
import sys
sys.path.insert(0, '$TOOLS_DIR')
import android_usb  # noqa: F401  (chi de kich hoat preload)
import usb1
usb1.USBContext().close()
" >/dev/null 2>&1; then
    check_pass "Thu vien native libusb-1.0.so: nap thanh cong."
else
    check_fail "Khong nap duoc libusb-1.0.so (co the thieu file .so du da 'pip install libusb1'). Chay: pkg install libusb && ls \$PREFIX/lib/libusb-1.0.so*"
fi

# 6. Firmware
for f in bootloader.bin partitions.bin boot_app0.bin firmware.bin; do
    if [ -f "$FIRMWARE_DIR/$f" ]; then
        check_pass "Firmware: $f co san."
    else
        check_warn "Firmware: thieu $f trong thu muc firmware/."
    fi
done

if [ -f "$FIRMWARE_DIR/littlefs.bin" ]; then
    check_pass "Firmware: littlefs.bin co san (se duoc nap kem)."
else
    log_info "Firmware: littlefs.bin khong co — bo qua (tuy chon, chi can neu project dung LittleFS)."
fi

# 7. Cau hinh
if [ -f "$CONFIG_DIR/config.json" ]; then
    check_pass "Cau hinh: config/config.json co san."
else
    check_warn "Cau hinh: thieu config/config.json, se dung gia tri mac dinh."
fi
if [ -f "$CONFIG_DIR/partition.json" ]; then
    check_pass "Cau hinh: config/partition.json co san."
else
    check_warn "Cau hinh: thieu config/partition.json, se dung gia tri mac dinh."
fi

# 8. Thiết bị USB đang cắm (chỉ liệt kê, không xin quyền)
log_info "Dang do tim thiet bi USB dang cam (khong xin quyen)..."
DEVICES_JSON="$(timeout 5 termux-usb -l 2>/dev/null)"
if [ -n "$DEVICES_JSON" ] && [ "$DEVICES_JSON" != "[]" ]; then
    check_pass "Phat hien thiet bi USB dang cam: $DEVICES_JSON"
    log_info "Chay './chipinfo.sh' de xac nhan day co phai ESP32 hay khong (se xin quyen USB)."
else
    check_warn "Khong phat hien thiet bi USB nao. Cam cap OTG + board ESP32 roi chay lai doctor.sh."
fi

echo
echo -e "${C_BOLD}===============================================${C_RESET}"
echo -e "Ket qua: ${C_GREEN}${PASS} PASS${C_RESET}  ${C_YELLOW}${WARN} WARNING${C_RESET}  ${C_RED}${FAIL} FAIL${C_RESET}"
echo -e "${C_BOLD}===============================================${C_RESET}"

if [ "$FAIL" -gt 0 ]; then
    log_error "Vui long khac phuc cac muc FAIL o tren truoc khi flash."
    exit 1
elif [ "$WARN" -gt 0 ]; then
    log_warn "Co mot so canh bao, nhung co the van flash duoc. Kiem tra lai neu gap loi."
    exit 0
else
    log_ok "Moi truong san sang! Chay './flash.sh' de bat dau."
    exit 0
fi
