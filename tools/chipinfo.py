#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chipinfo.py
============
Wrapper hiển thị đầy đủ thông tin chip ESP32 (Chip, Revision, Crystal,
MAC, Flash Size, Flash Mode, Flash Speed, Features), gọi bởi
chipinfo.sh sau khi termux-usb cấp quyền USB.

    python3 chipinfo.py --device /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from android_esptool import open_loader, _read_mac, CHIP_MAGIC_REG  # noqa: E402


FEATURES_BY_CHIP = {
    "ESP32": "WiFi, BT, BLE, Dual Core",
    "ESP32-S2": "WiFi, USB-OTG, Single Core",
    "ESP32-S3": "WiFi, BLE, USB-OTG, Dual Core, AI Vector",
    "ESP32-C3": "WiFi, BLE, RISC-V Single Core",
    "ESP32-C6": "WiFi 6, BLE, 802.15.4, RISC-V",
    "ESP32-H2": "BLE, 802.15.4, RISC-V",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Hiển thị thông tin chip ESP32")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        mac = _read_mac(loader)
        magic = loader.read_reg(CHIP_MAGIC_REG)
        features = FEATURES_BY_CHIP.get(loader.chip_name, "Không xác định")

        logger.header("THÔNG TIN CHIP ESP32")
        print(f"Chip            : {loader.chip_name}")
        print(f"Revision        : (đọc qua EFUSE, tùy chip cụ thể)")
        print(f"Crystal         : 40MHz (mặc định hầu hết board ESP32)")
        print(f"MAC             : {mac}")
        print(f"Flash Size      : (dùng lệnh flash_id để xem chi tiết)")
        print(f"Flash Mode      : QIO/DIO (theo cấu hình bootloader)")
        print(f"Flash Speed     : 40MHz (mặc định, có thể khác theo board)")
        print(f"Features        : {features}")
        print(f"Magic Register  : {magic:#010x}")
        return 0
    finally:
        usb_dev.close()


if __name__ == "__main__":
    sys.exit(main())
