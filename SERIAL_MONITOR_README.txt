SERIAL MONITOR - ESP32 USB FLASHER v3

Menu: chọn 15. Serial Monitor / trạng thái firmware
Baud mặc định: 115200
Có thể chọn Reset = C để reset bằng DTR/RTS và bắt boot log.
Ctrl+C để dừng monitor.

CLI:
  ./start.sh --menu
  python esp32_usb_flasher.py --monitor --baud 115200 --reset

Lưu ý: Serial Monitor không đưa ESP32 vào Download Mode và không flash/erase.
Nó chỉ cấu hình CP210x 8N1 và đọc USB Bulk IN. Tùy chọn --reset chỉ reset chip
bằng DTR/RTS trước khi bắt đầu đọc log.
