#!/data/data/com.termux/files/usr/bin/bash
# menu.sh
# =======
# Menu trung tâm cho esp32-android-toolkit — chỉ cần chạy:
#   ./menu.sh
# rồi chọn số tương ứng, không cần nhớ tên từng script.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

C_RESET='\033[0m'; C_BOLD='\033[1m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'; C_GREEN='\033[32m'

show_menu() {
    clear
    echo -e "${C_BOLD}${C_CYAN}"
    echo "═══════════════════════════════════════════"
    echo "   ESP32 ANDROID TOOLKIT — MENU"
    echo "═══════════════════════════════════════════"
    echo -e "${C_RESET}"
    echo -e "${C_GREEN} 1)${C_RESET} doctor.sh    - Kiểm tra môi trường (chạy trước tiên nếu chưa chắc)"
    echo -e "${C_GREEN} 2)${C_RESET} install.sh   - Cài đặt dependency lần đầu"
    echo -e "${C_GREEN} 3)${C_RESET} flash.sh     - Nạp firmware vào ESP32"
    echo -e "${C_GREEN} 4)${C_RESET} erase.sh     - Xóa toàn bộ flash ESP32"
    echo -e "${C_GREEN} 5)${C_RESET} chipinfo.sh  - Xem thông tin chip đang cắm"
    echo -e "${C_GREEN} 6)${C_RESET} mac.sh       - In địa chỉ MAC"
    echo -e "${C_GREEN} 7)${C_RESET} monitor.sh   - Mở Serial Monitor"
    echo -e "${C_GREEN} 8)${C_RESET} update.sh    - Cập nhật toolkit (git pull + dependency)"
    echo -e "${C_YELLOW} 0)${C_RESET} Thoát"
    echo
}

run() {
    local script="$1"
    if [ ! -f "$script" ]; then
        echo -e "${C_YELLOW}Không tìm thấy $script${C_RESET}"
        return
    fi
    chmod +x "$script" 2>/dev/null
    echo
    "./$script"
    echo
    read -n 1 -s -r -p "Nhấn phím bất kỳ để quay lại menu..."
}

while true; do
    show_menu
    read -r -p "Chọn số: " choice
    case "$choice" in
        1) run doctor.sh ;;
        2) run install.sh ;;
        3) run flash.sh ;;
        4) run erase.sh ;;
        5) run chipinfo.sh ;;
        6) run mac.sh ;;
        7) run monitor.sh ;;
        8) run update.sh ;;
        0) echo "Tạm biệt!"; exit 0 ;;
        *) echo -e "${C_YELLOW}Lựa chọn không hợp lệ.${C_RESET}"; sleep 1 ;;
    esac
done
