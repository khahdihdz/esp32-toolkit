#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_monitor.py
===================
Serial Monitor thuần Python cho ESP32 trên Android/Termux, không dùng
PlatformIO, không dùng pySerial. Đọc dữ liệu UART qua UartBridge (bulk
transfer USB) và hiển thị theo thời gian thực.

Cách gọi (được monitor.sh gọi gián tiếp qua termux-usb -r -e, với
đường dẫn thiết bị được termux-usb tự thêm vào cuối dòng lệnh):

    python3 serial_monitor.py --baud 115200 --log session.log
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from android_usb_raw import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from uart_bridge import create_bridge, UartBridgeError  # noqa: E402
from logger import Colors  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial Monitor cho ESP32 trên Android/Termux")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mặc định 115200)")
    parser.add_argument("--log", default=None, help="Đường dẫn file để lưu log")
    parser.add_argument("--filter", default=None, help="Regex để lọc dòng hiển thị")
    parser.add_argument("--no-timestamp", action="store_true", help="Tắt timestamp")
    parser.add_argument("--no-color", action="store_true", help="Tắt màu ANSI")
    parser.add_argument("device", help="Đường dẫn thiết bị USB (do termux-usb tự thêm vào)")
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

    filter_re = re.compile(args.filter) if args.filter else None
    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    logger.header("ESP32 SERIAL MONITOR")
    logger.info(f"Thiết bị : {args.device}")
    logger.info(f"Baudrate : {args.baud}")
    if args.log:
        logger.info(f"Lưu log  : {args.log}")
    logger.info("Nhấn Ctrl+C để thoát.\n")

    reconnect_delay = 1.0
    line_buf = bytearray()

    while True:
        usb_dev = AndroidUsbDevice(args.device)
        try:
            usb_dev.open()
            vendor_id, product_id = usb_dev.get_device_descriptor()
            bridge = create_bridge(usb_dev, vendor_id, product_id)
            bridge.open()
            bridge.set_baudrate(args.baud)
            reconnect_delay = 1.0
            logger.ok("Đã kết nối UART. Đang lắng nghe dữ liệu...\n")

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

                    display_line = ts + text
                    if not args.no_color:
                        display_line = (
                            ts + colorize_line(text) if ts else colorize_line(text)
                        )
                    print(display_line)

                    if log_file:
                        log_file.write(f"{ts}{text}\n")
                        log_file.flush()

        except KeyboardInterrupt:
            logger.warning("\nĐã dừng Serial Monitor.")
            return 0
        except (AndroidUsbError, UartBridgeError) as exc:
            logger.error(f"Mất kết nối UART: {exc}")
            logger.info(f"Thử kết nối lại sau {reconnect_delay:.0f} giây...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 10.0)
        finally:
            usb_dev.close()
            if log_file:
                log_file.flush()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
