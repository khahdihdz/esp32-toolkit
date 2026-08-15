#!/data/data/com.termux/files/usr/bin/bash
set -e
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
ROOT="/data/data/com.termux/files/home/esp32-toolkit"
cat > "$PREFIX/bin/espflash-usb-callback" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
set -e
ROOT="/data/data/com.termux/files/home/esp32-toolkit"
PYTHON="/data/data/com.termux/files/usr/bin/python"
exec "$PYTHON" -u "$ROOT/usb_worker.py" "$@"
EOF
chmod 755 "$PREFIX/bin/espflash-usb-callback"
echo "[OK] Đã cài callback: $PREFIX/bin/espflash-usb-callback"
