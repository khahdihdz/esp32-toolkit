#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bootloader.py
=============
Ghép nối AndroidUsbDevice -> UartBridge (driver phù hợp, tự nhận diện
theo VID/PID) -> EspRomLoader, rồi đưa chip vào chế độ download (ROM
bootloader) và đồng bộ giao thức.

Đây là điểm hội tụ duy nhất giữa lớp USB và lớp giao thức ESP, được
gọi từ BÊN TRONG một phiên quyền `termux-usb -r -e` duy nhất (xem
usb_detect.py để biết lý do đây là điểm cải tiến kiến trúc chính so
với V1).
"""

from __future__ import annotations

import sys
import os
from typing import Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
import config as toolkit_config  # noqa: E402
from android_usb import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from usb_bridge import create_bridge, UartBridge, UartBridgeError  # noqa: E402
from esp_loader import EspRomLoader, EspLoaderError, DEFAULT_RESET_BAUD  # noqa: E402


class BootloaderError(RuntimeError):
    pass


def open_loader(device_path: str, reset_baud: int = None) -> Tuple[AndroidUsbDevice, EspRomLoader]:
    """
    Mở thiết bị USB (đã được cấp quyền), tự nhận diện driver UART theo
    VID/PID, và trả về (usb_dev, loader) sẵn sàng để gọi loader.connect().

    Người gọi chịu trách nhiệm usb_dev.close() khi xong (khuyến khích
    dùng try/finally).
    """
    cfg = toolkit_config.load_config()
    if reset_baud is None:
        reset_baud = int(cfg.get("reset_baud", DEFAULT_RESET_BAUD))

    usb_dev = AndroidUsbDevice(device_path)
    try:
        usb_dev.open()
    except AndroidUsbError as exc:
        raise BootloaderError(str(exc)) from exc

    try:
        vendor_id, product_id = usb_dev.get_device_descriptor()
        logger.info(f"Thiet bi USB: VID={vendor_id:04x} PID={product_id:04x}")

        known = toolkit_config.known_uart_chips()
        name = known.get((vendor_id, product_id))
        if name:
            logger.info(f"Nhan dien chip UART-USB: {name}")

        bridge = create_bridge(usb_dev, vendor_id, product_id)
        bridge.open()
        bridge.set_baud(reset_baud)
        loader = EspRomLoader(bridge)
        return usb_dev, loader
    except (AndroidUsbError, UartBridgeError) as exc:
        usb_dev.close()
        raise BootloaderError(str(exc)) from exc


def connect(
    device_path: str,
    reset_baud: int = None,
    max_retries: int = None,
) -> Tuple[AndroidUsbDevice, EspRomLoader]:
    """Mở thiết bị, chọn driver, và đồng bộ ROM bootloader. Sẵn sàng để flash/erase/read."""
    cfg = toolkit_config.load_config()
    if max_retries is None:
        max_retries = int(cfg.get("sync_max_retries", 5))

    usb_dev, loader = open_loader(device_path, reset_baud=reset_baud)
    try:
        loader.connect(max_retries=max_retries)
        return usb_dev, loader
    except EspLoaderError as exc:
        usb_dev.close()
        raise BootloaderError(str(exc)) from exc


def reset_only(device_path: str) -> None:
    """Chỉ mở UART và thực hiện reset cứng ESP32, không cần sync ROM loader."""
    usb_dev, loader = open_loader(device_path)
    try:
        loader.hard_reset()
    finally:
        usb_dev.close()
