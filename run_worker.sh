#!/data/data/com.termux/files/usr/bin/bash
# termux-usb -e truyền USB FD vào argument cuối của callback.
exec /data/data/com.termux/files/usr/bin/python -u   /data/data/com.termux/files/home/esp32-toolkit/usb_worker.py "$@"
