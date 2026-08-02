#!/data/data/com.termux/files/usr/bin/bash
# update.sh
# =========
# Cập nhật dự án từ Git (nếu là git repo) và cài lại dependency nếu
# thiếu.
#   ./update.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/common.sh
source "$SCRIPT_DIR/tools/common.sh"

cd "$ROOT_DIR"

if [ -d ".git" ]; then
    log_info "Đang kiểm tra cập nhật từ Git..."
    git fetch --all
    LOCAL_HASH="$(git rev-parse HEAD)"
    REMOTE_HASH="$(git rev-parse @{u} 2>/dev/null || echo "$LOCAL_HASH")"
    if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
        log_info "Có bản cập nhật mới, đang kéo về..."
        git pull --ff-only
        log_ok "Đã cập nhật dự án lên phiên bản mới nhất."
    else
        log_ok "Dự án đã ở phiên bản mới nhất."
    fi
else
    log_warn "Thư mục hiện tại không phải Git repo, bỏ qua bước git pull."
fi

log_info "Kiểm tra lại dependency..."
python3 -m pip install --upgrade libusb1 >/dev/null 2>&1 || log_warn "Không cập nhật được libusb1 qua pip."

log_ok "Cập nhật hoàn tất. Chạy './doctor.sh' để kiểm tra lại môi trường."
