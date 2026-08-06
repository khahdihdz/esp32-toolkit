#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
esptool_android.py
===================
CLI thống nhất cho ESP32 Android Toolkit V2. Gọi bởi các script bash
(flash.sh, erase.sh, chipinfo.sh, mac.sh) thông qua MỘT phiên
`termux-usb -r -e` DUY NHẤT — đường dẫn thiết bị được termux-usb tự
động thêm vào cuối dòng lệnh, khớp với tham số `--device`.

Sử dụng:
    esptool_android.py sync         --device /dev/bus/usb/001/002
    esptool_android.py chip_id      --device /dev/bus/usb/001/002
    esptool_android.py read_mac     --device /dev/bus/usb/001/002
    esptool_android.py flash_id     --device /dev/bus/usb/001/002
    esptool_android.py erase_flash  --device /dev/bus/usb/001/002
    esptool_android.py flash_auto   --device /dev/... [--flash-baud N]
    esptool_android.py write_flash  --device /dev/... \\
        0x1000 firmware/bootloader.bin 0x8000 firmware/partitions.bin ...
    esptool_android.py read_flash   --device /dev/... 0x10000 0x100000 out.bin
    esptool_android.py verify_flash --device /dev/... 0x10000 firmware/firmware.bin
    esptool_android.py image_info   firmware/firmware.bin
    esptool_android.py reset        --device /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
import config as toolkit_config  # noqa: E402
import bootloader  # noqa: E402
import firmware  # noqa: E402
from android_usb import AndroidUsbError  # noqa: E402
from usb_bridge import UartBridgeError  # noqa: E402
from esp_loader import EspLoaderError, DEFAULT_FLASH_BAUD, DEFAULT_RESET_BAUD  # noqa: E402
from bootloader import BootloaderError  # noqa: E402
from firmware import FirmwareError  # noqa: E402
from utils import check_file_exists, format_size  # noqa: E402


ALL_ERRORS = (EspLoaderError, UartBridgeError, AndroidUsbError, BootloaderError, FirmwareError)


# --------------------------------------------------------------------------
# Lệnh
# --------------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        logger.ok(f"Ket noi thanh cong. Chip: {loader.chip_name}")
        return 0
    finally:
        usb_dev.close()


def cmd_chip_id(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        mac = loader.read_mac()
        print(f"Chip            : {loader.chip_name}")
        print(f"MAC             : {mac}")
        print(f"Magic Register  : {loader.chip_magic:#010x}")
        return 0
    finally:
        usb_dev.close()


def cmd_read_mac(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        print(f"MAC:\n{loader.read_mac()}")
        return 0
    finally:
        usb_dev.close()


def cmd_flash_id(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        loader.spi_attach()
        print(f"Chip            : {loader.chip_name}")
        print("Flash Mode      : QIO/DIO (tu dong, theo cau hinh bootloader)")
        print("Flash Speed     : 40MHz (mac dinh, co the khac theo board)")
        return 0
    finally:
        usb_dev.close()


def cmd_erase_flash(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        print("Connecting...")
        firmware.erase_flash(loader)
        return 0
    finally:
        usb_dev.close()


def _parse_offset_file_pairs(pairs: List[str]) -> List[Tuple[int, str]]:
    if len(pairs) % 2 != 0:
        raise FirmwareError("Tham so write_flash phai theo cap: <offset> <file> ...")
    entries: List[Tuple[int, str]] = []
    for i in range(0, len(pairs), 2):
        offset = int(pairs[i], 0)
        path = pairs[i + 1]
        if not check_file_exists(path):
            raise FirmwareError(f"Khong tim thay file: {path}")
        entries.append((offset, path))
    return entries


def cmd_write_flash(args: argparse.Namespace) -> int:
    entries = _parse_offset_file_pairs(args.offset_file)
    usb_dev, loader = bootloader.connect(args.device)
    try:
        firmware.write_flash_files(loader, entries, flash_baud=args.flash_baud)
        return 0
    finally:
        usb_dev.close()


def cmd_flash_auto(args: argparse.Namespace) -> int:
    """Tự động lấy offset + file từ config/partition.json và firmware/."""
    entries = firmware.resolve_auto_entries(include_optional=True)
    if not entries:
        logger.error("Khong co file firmware nao de ghi.")
        return 1
    usb_dev, loader = bootloader.connect(args.device)
    try:
        firmware.write_flash_files(loader, entries, flash_baud=args.flash_baud)
        return 0
    finally:
        usb_dev.close()


def cmd_read_flash(args: argparse.Namespace) -> int:
    usb_dev, loader = bootloader.connect(args.device)
    try:
        loader.spi_attach()
        offset = int(args.offset, 0)
        size = int(args.size, 0)
        firmware.read_flash_to_file(loader, offset, size, args.output)
        return 0
    finally:
        usb_dev.close()


def cmd_verify_flash(args: argparse.Namespace) -> int:
    entries = _parse_offset_file_pairs(args.offset_file)
    usb_dev, loader = bootloader.connect(args.device)
    try:
        loader.spi_attach()
        all_ok = True
        for offset, path in entries:
            ok = firmware.verify_flash(loader, offset, path)
            if not ok:
                all_ok = False
        return 0 if all_ok else 1
    finally:
        usb_dev.close()


def cmd_image_info(args: argparse.Namespace) -> int:
    try:
        info = firmware.image_info(args.file)
    except FirmwareError as exc:
        logger.error(str(exc))
        return 1
    print(f"Magic           : {info['magic']:#04x}")
    print(f"So segment      : {info['num_segments']}")
    print(f"Flash Mode      : {info['flash_mode']}")
    print(f"Flash Size      : {info['flash_size']}")
    print(f"Flash Speed     : {info['flash_speed']}")
    print(f"Entry Point     : {info['entry_point']:#010x}")
    print(f"Kich thuoc file : {format_size(info['file_size'])}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    bootloader.reset_only(args.device)
    logger.ok("Da reset ESP32.")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esptool_android.py",
        description="Cong cu nap/doc/xoa flash ESP32 thuan Python cho Android/Termux (Android USB Host + termux-usb).",
    )
    parser.add_argument("-v", "--debug", action="store_true", help="Bat log debug chi tiet")
    sub = parser.add_subparsers(dest="action", required=True)

    def add_device_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("--device", required=True, help="Duong dan thiet bi USB (vd: /dev/bus/usb/001/002)")

    p = sub.add_parser("sync", help="Kiem tra ket noi va dong bo voi ROM bootloader")
    add_device_arg(p)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("chip_id", help="Doc thong tin chip")
    add_device_arg(p)
    p.set_defaults(func=cmd_chip_id)

    p = sub.add_parser("read_mac", help="Doc dia chi MAC")
    add_device_arg(p)
    p.set_defaults(func=cmd_read_mac)

    p = sub.add_parser("flash_id", help="Doc thong tin flash SPI")
    add_device_arg(p)
    p.set_defaults(func=cmd_flash_id)

    p = sub.add_parser("erase_flash", help="Xoa toan bo flash")
    add_device_arg(p)
    p.set_defaults(func=cmd_erase_flash)

    p = sub.add_parser("write_flash", help="Ghi firmware vao flash (chi dinh offset/file thu cong)")
    add_device_arg(p)
    p.add_argument("--flash-baud", type=int, default=DEFAULT_FLASH_BAUD, help="Baudrate khi ghi flash")
    p.add_argument("offset_file", nargs="+", help="Cap <offset> <file> ... vd: 0x1000 bootloader.bin")
    p.set_defaults(func=cmd_write_flash)

    p = sub.add_parser("flash_auto", help="Ghi firmware tu dong theo config/partition.json + firmware/")
    add_device_arg(p)
    p.add_argument("--flash-baud", type=int, default=DEFAULT_FLASH_BAUD, help="Baudrate khi ghi flash")
    p.set_defaults(func=cmd_flash_auto)

    p = sub.add_parser("read_flash", help="Doc flash ra file")
    add_device_arg(p)
    p.add_argument("offset")
    p.add_argument("size")
    p.add_argument("output")
    p.set_defaults(func=cmd_read_flash)

    p = sub.add_parser("verify_flash", help="So sanh MD5 file local voi flash tren chip")
    add_device_arg(p)
    p.add_argument("offset_file", nargs="+", help="Cap <offset> <file> ... vd: 0x1000 bootloader.bin")
    p.set_defaults(func=cmd_verify_flash)

    p = sub.add_parser("image_info", help="Hien thi thong tin firmware image (khong can thiet bi)")
    p.add_argument("file")
    p.set_defaults(func=cmd_image_info)

    p = sub.add_parser("reset", help="Reset (khoi dong lai) ESP32")
    add_device_arg(p)
    p.set_defaults(func=cmd_reset)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ALL_ERRORS as exc:
        logger.error(str(exc))
        return 1
    except KeyboardInterrupt:
        logger.warning("Da huy boi nguoi dung.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
