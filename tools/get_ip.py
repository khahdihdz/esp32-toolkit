#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_ip.py
=========
Reset ESP32, lang nghe UART cho toi khi thay dong log in dia chi IP
(vd: firmware kieu "khong_gian_xanh" in "[WIFI] Da ket noi. IP: ..."
hoac "Che do AP da bat ... IP: ..."), roi in ra va thoat — khong can
ngoi xem Serial Monitor thu cong.

Duoc get_ip.sh goi ben trong MOT phien `termux-usb -r -e` duy nhat,
device path duoc termux-usb tu them vao cuoi dong lenh:

    python3 get_ip.py --baud 115200 --timeout 20 /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from android_usb import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from usb_bridge import create_bridge, UartBridgeError  # noqa: E402

# Khop cac dang dong log in IP pho bien (vd: "[WIFI] Da ket noi. IP: 192.168.1.42",
# "IP: 192.168.4.1", "IP Address: ...", ...). Bat dia chi IPv4 dau tien trong dong.
IP_LINE_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
IP_HINT_RE = re.compile(r"ip[^a-zA-Z]", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Doc dia chi IP ma firmware ESP32 in ra qua Serial")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mac dinh 115200)")
    parser.add_argument("--timeout", type=int, default=20, help="So giay toi da cho (mac dinh 20)")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Khong tu dong reset qua DTR/RTS - tu bam nut RESET/EN vat ly ngay khi thay dong "
        "'Dang lang nghe...' xuat hien",
    )
    parser.add_argument("device", help="Duong dan thiet bi USB (do termux-usb tu them vao)")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    logger.header("XEM DIA CHI IP")
    logger.info(f"Thiet bi : {args.device}")
    logger.info(f"Baudrate : {args.baud}")
    logger.info(f"Timeout  : {args.timeout}s")
    logger.info("Dang reset ESP32 va cho firmware ket noi WiFi...\n")

    usb_dev = AndroidUsbDevice(args.device)
    line_buf = bytearray()
    found = []

    try:
        usb_dev.open()
        vendor_id, product_id = usb_dev.get_device_descriptor()
        bridge = create_bridge(usb_dev, vendor_id, product_id)
        bridge.open()
        bridge.set_baud(args.baud)

        if args.no_reset:
            logger.info("Bo qua auto-reset (--no-reset). Hay bam nut RESET/EN vat ly ngay bay gio.\n")
        else:
            try:
                bridge.hard_reset()
            except Exception as exc:
                logger.warning(f"Khong the reset ESP32 tu dong: {exc}")
            logger.info("Dang lang nghe... (neu khong thay log, bam nut RESET/EN vat ly tren mach)\n")

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            chunk = bridge.read_available(max_size=2048, timeout_ms=200)
            if not chunk:
                continue
            line_buf.extend(chunk)
            while b"\n" in line_buf:
                raw_line, _, rest = line_buf.partition(b"\n")
                line_buf = bytearray(rest)
                text = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                if not text:
                    continue
                print(text)
                if IP_HINT_RE.search(text):
                    m = IP_LINE_RE.search(text)
                    if m and m.group(1) not in found:
                        found.append(m.group(1))
                        logger.ok(f"Tim thay dia chi IP: {m.group(1)}")
                        return 0

        if found:
            logger.ok(f"Dia chi IP: {found[0]}")
            return 0

        logger.error(
            "Khong thay dong log chua dia chi IP trong thoi gian cho. "
            "Kiem tra ESP32 da flash firmware co in IP qua Serial chua, "
            "hoac tang --timeout."
        )
        return 1

    except (AndroidUsbError, UartBridgeError) as exc:
        logger.error(f"Mat ket noi UART: {exc}")
        return 1
    except KeyboardInterrupt:
        logger.warning("\nDa dung.")
        return 0
    finally:
        usb_dev.close()


if __name__ == "__main__":
    sys.exit(main())
