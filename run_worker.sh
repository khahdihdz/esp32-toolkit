#!/data/data/com.termux/files/usr/bin/bash
# termux-usb -e truyền USB FD vào argument cuối của callback.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"

exec "${PYTHON:-$PREFIX/bin/python}" -u "$BASE/usb_worker.py" "$@"
