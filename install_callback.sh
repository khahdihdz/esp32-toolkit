#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
# Repo = thư mục chứa script cài đặt này (bỏ hard-code đường dẫn tuyệt đối).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$PREFIX/bin/python}"
CALLBACK="$PREFIX/bin/espflash-usb-callback"

cat > "$CALLBACK" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
exec "$PYTHON" -u "$ROOT/usb_worker.py" "\$@"
EOF

chmod 755 "$CALLBACK"
echo "[OK] Đã cài callback: $CALLBACK"
