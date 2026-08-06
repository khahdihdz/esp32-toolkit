#!/data/data/com.termux/files/usr/bin/bash
# menu.sh
# =======
# Menu trung tam cho ESP32 Android Toolkit V2 — chi can chay:
#   ./menu.sh
# roi chon so tuong ung, khong can nho ten tung script.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

C_RESET='\033[0m'; C_BOLD='\033[1m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'; C_GREEN='\033[32m'

show_menu() {
    clear
    echo -e "${C_BOLD}${C_CYAN}"
    echo "==============================================="
    echo "   ESP32 ANDROID TOOLKIT V2 — MENU"
    echo "   (Android USB Host + termux-usb, khong root)"
    echo "==============================================="
    echo -e "${C_RESET}"
    echo -e "${C_GREEN} 1)${C_RESET} doctor.sh    - Kiem tra moi truong (chay truoc tien neu chua chac)"
    echo -e "${C_GREEN} 2)${C_RESET} install.sh   - Cai dat dependency lan dau"
    echo -e "${C_GREEN} 3)${C_RESET} flash.sh     - Nap firmware vao ESP32"
    echo -e "${C_GREEN} 4)${C_RESET} erase.sh     - Xoa toan bo flash ESP32"
    echo -e "${C_GREEN} 5)${C_RESET} chipinfo.sh  - Xem thong tin chip dang cam"
    echo -e "${C_GREEN} 6)${C_RESET} mac.sh       - In dia chi MAC"
    echo -e "${C_GREEN} 7)${C_RESET} monitor.sh   - Mo Serial Monitor"
    echo -e "${C_GREEN} 8)${C_RESET} update.sh    - Cap nhat toolkit (git pull + dependency)"
    echo -e "${C_GREEN} 9)${C_RESET} verify.sh    - So sanh MD5 firmware da flash voi file goc"
    echo -e "${C_GREEN}10)${C_RESET} get_ip.sh    - Xem dia chi IP (WiFi) cua ESP32"
    echo -e "${C_YELLOW} 0)${C_RESET} Thoat"
    echo
}

run() {
    local script="$1"
    if [ ! -f "$script" ]; then
        echo -e "${C_YELLOW}Khong tim thay $script${C_RESET}"
        return
    fi
    chmod +x "$script" 2>/dev/null
    echo
    "./$script"
    echo
    read -n 1 -s -r -p "Nhan phim bat ky de quay lai menu..."
}

while true; do
    show_menu
    read -r -p "Chon so: " choice
    case "$choice" in
        1) run doctor.sh ;;
        2) run install.sh ;;
        3) run flash.sh ;;
        4) run erase.sh ;;
        5) run chipinfo.sh ;;
        6) run mac.sh ;;
        7) run monitor.sh ;;
        8) run update.sh ;;
        9) run verify.sh ;;
        10) run get_ip.sh ;;
        0) echo "Tam biet!"; exit 0 ;;
        *) echo -e "${C_YELLOW}Lua chon khong hop le.${C_RESET}"; sleep 1 ;;
    esac
done
