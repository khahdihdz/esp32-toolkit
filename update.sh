#!/data/data/com.termux/files/usr/bin/bash
# update.sh
# =========
# Cap nhat du an tu Git (neu la git repo) va cai lai dependency neu
# thieu.
#   ./update.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

cd "$ROOT_DIR"

if [ -d ".git" ]; then
    log_info "Dang kiem tra cap nhat tu Git..."
    git fetch --all
    LOCAL_HASH="$(git rev-parse HEAD)"
    REMOTE_HASH="$(git rev-parse @{u} 2>/dev/null || echo "$LOCAL_HASH")"
    if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
        log_info "Co ban cap nhat moi, dang keo ve..."
        git pull --ff-only
        log_ok "Da cap nhat du an len phien ban moi nhat."
    else
        log_ok "Du an da o phien ban moi nhat."
    fi
else
    log_warn "Thu muc hien tai khong phai Git repo, bo qua buoc git pull."
fi

log_info "Kiem tra lai dependency..."
python3 -m pip install --upgrade libusb1 --break-system-packages >/dev/null 2>&1 || \
    python3 -m pip install --upgrade libusb1 >/dev/null 2>&1 || \
    log_warn "Khong cap nhat duoc libusb1 qua pip."

log_ok "Cap nhat hoan tat. Chay './doctor.sh' de kiem tra lai moi truong."
