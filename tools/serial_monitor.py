#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_monitor.py
==================
Serial Monitor thuần Python cho ESP32 trên Android/Termux, không dùng
PlatformIO, không dùng pySerial. Đọc dữ liệu UART qua UartBridge (bulk
transfer USB) và hiển thị theo thời gian thực, tự động reconnect nếu
mất kết nối.

Được monitor.sh gọi bên trong MỘT phiên `termux-usb -r -e` duy nhất,
với đường dẫn thiết bị được termux-usb tự thêm vào cuối dòng lệnh:

    python3 serial_monitor.py --baud 115200 --log session.log /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
import config as toolkit_config  # noqa: E402
from logger import Colors  # noqa: E402
from android_usb import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from usb_bridge import create_bridge, UartBridgeError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial Monitor cho ESP32 tren Android/Termux")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mac dinh 115200)")
    parser.add_argument("--log", default=None, help="Duong dan file de luu log")
    parser.add_argument("--filter", default=None, help="Regex de loc dong hien thi")
    parser.add_argument("--no-timestamp", action="store_true", help="Tat timestamp")
    parser.add_argument("--no-color", action="store_true", help="Tat mau ANSI")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Khong tu dong reset qua DTR/RTS - dung khi board khong co mach auto-reset "
        "hoac dau day DTR/RTS khac chuan (tu bam nut RESET/EN vat ly thay the)",
    )
    parser.add_argument("device", help="Duong dan thiet bi USB (do termux-usb tu them vao)")
    return parser


def colorize_line(line: str) -> str:
    """Tô màu đơn giản theo mức log phổ biến của ESP-IDF (E/W/I/D)."""
    if re.match(r"^\s*E \(", line) or " error" in line.lower():
        return f"{Colors.RED}{line}{Colors.RESET}"
    if re.match(r"^\s*W \(", line) or "warn" in line.lower():
        return f"{Colors.YELLOW}{line}{Colors.RESET}"
    if re.match(r"^\s*I \(", line):
        return f"{Colors.GREEN}{line}{Colors.RESET}"
    return line


def main() -> int:
    args = build_parser().parse_args()
    cfg = toolkit_config.load_config()

    filter_re = re.compile(args.filter) if args.filter else None
    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    logger.header("ESP32 SERIAL MONITOR")
    logger.info(f"Thiet bi : {args.device}")
    logger.info(f"Baudrate : {args.baud}")
    if args.log:
        logger.info(f"Luu log  : {args.log}")
    logger.info("Nhan Ctrl+C de thoat.\n")

    reconnect_delay = float(cfg.get("reconnect_initial_delay_sec", 1))
    reconnect_max = float(cfg.get("reconnect_max_delay_sec", 10))
    line_buf = bytearray()

    while True:
        usb_dev = AndroidUsbDevice(args.device)
        try:
            usb_dev.open()
            vendor_id, product_id = usb_dev.get_device_descriptor()
            bridge = create_bridge(usb_dev, vendor_id, product_id)
            bridge.open()
            bridge.set_baud(args.baud)
            reconnect_delay = float(cfg.get("reconnect_initial_delay_sec", 1))

            # Reset ESP32 khi vua ket noi, giong hanh vi cua Arduino IDE /
            # PlatformIO monitor: neu khong reset, cac dong log chi in MOT
            # LAN trong setup() (vd: log WiFi AP mode) da troi qua tu luc
            # flash xong se KHONG BAO GIO xuat hien, vi loop() co the khong
            # in gi them. Reset o day dam bao luon thay lai tu dau.
            try:
                if args.no_reset:
                    logger.info("Bo qua auto-reset (--no-reset).")
                    logger.warning(
                        "Neu khong thay log, hay BAM NUT RESET/EN vat ly tren mach NGAY BAY GIO.\n"
                    )
                else:
                    bridge.hard_reset()
                    logger.info("Da reset ESP32, cho khoi dong lai...")
                    logger.warning(
                        "Neu sau vai giay van khong thay log gi, mach co the khong co "
                        "mach auto-reset qua DTR/RTS - hay BAM NUT RESET/EN vat ly, "
                        "hoac chay lai voi bien NO_RESET=1.\n"
                    )
            except Exception as exc:  # không nghiêm trọng, vẫn tiếp tục lắng nghe
                logger.warning(f"Khong the reset ESP32 tu dong: {exc}")

            logger.ok("Da ket noi UART. Dang lang nghe du lieu...\n")

            while True:
                chunk = bridge.read_available(max_size=2048, timeout_ms=200)
                if not chunk:
                    continue
                line_buf.extend(chunk)
                while b"\n" in line_buf:
                    raw_line, _, rest = line_buf.partition(b"\n")
                    line_buf = bytearray(rest)
                    text = raw_line.decode("utf-8", errors="replace").rstrip("\r")

                    if filter_re and not filter_re.search(text):
                        continue

                    ts = ""
                    if not args.no_timestamp:
                        ts = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] "

                    display_line = ts + (colorize_line(text) if not args.no_color else text)
                    print(display_line)

                    if log_file:
                        log_file.write(f"{ts}{text}\n")
                        log_file.flush()

        except KeyboardInterrupt:
            logger.warning("\nDa dung Serial Monitor.")
            return 0
        except (AndroidUsbError, UartBridgeError) as exc:
            logger.error(f"Mat ket noi UART: {exc}")
            logger.info(f"Thu ket noi lai sau {reconnect_delay:.0f} giay...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, reconnect_max)
        finally:
            usb_dev.close()
            if log_file:
                log_file.flush()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
