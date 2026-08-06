#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_bridge.py
=============
Giao diện trừu tượng dùng chung cho mọi driver UART-qua-USB (thay thế
hoàn toàn pySerial, vốn cần tty node mà Android không cấp cho ứng
dụng thường).

Mỗi driver cụ thể (cp210x.py, ch340.py, ftdi.py, cdc_acm.py) triển
khai lớp con của UartBridge với:

    detect(vid, pid)            - classmethod, có nhận diện được VID/PID này không
    open()                      - khởi tạo UART, claim interface, tìm endpoint
    set_baud(baud)               - đổi tốc độ baud
    set_dtr(state) / set_rts(state) - điều khiển từng chân riêng lẻ
    read(size, timeout_ms)      - đọc bytes từ UART (bulk IN)
    write(data)                 - ghi bytes ra UART (bulk OUT)
    flush()                     - xả buffer đọc còn sót lại
    close()                     - nhả interface

Giá trị thanh ghi/lệnh vendor lấy từ tài liệu driver Linux mã nguồn mở
(cp210x.c, ch341.c, ftdi_sio.c) — đây là giao thức USB công khai,
không phải bí mật thương mại.
"""

from __future__ import annotations

import sys
import time
import os
from abc import ABC, abstractmethod
from typing import Optional, Type

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from android_usb import AndroidUsbDevice, AndroidUsbError  # noqa: E402
import logger  # noqa: E402


class UartBridgeError(RuntimeError):
    pass


class UartBridge(ABC):
    """Giao diện chung cho mọi chip USB-UART / USB-CDC."""

    #: Tên hiển thị, driver con phải override.
    NAME = "unknown"

    def __init__(self, usb_dev: AndroidUsbDevice, interface: int = 0) -> None:
        self.usb_dev = usb_dev
        self.interface = interface
        self.ep_in: Optional[int] = None
        self.ep_out: Optional[int] = None
        self._dtr = False
        self._rts = False

    # ---- driver con phải triển khai -----------------------------------
    @classmethod
    @abstractmethod
    def detect(cls, vendor_id: int, product_id: int) -> bool:
        """Trả về True nếu driver này xử lý được VID/PID đưa vào."""
        ...

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def set_baud(self, baud: int) -> None: ...

    @abstractmethod
    def _set_modem_lines(self, dtr: bool, rts: bool) -> None: ...

    # ---- hành vi dùng chung ---------------------------------------------
    def set_dtr(self, state: bool) -> None:
        self._set_modem_lines(dtr=state, rts=self._rts)

    def set_rts(self, state: bool) -> None:
        self._set_modem_lines(dtr=self._dtr, rts=state)

    def set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        self._set_modem_lines(dtr=dtr, rts=rts)

    def write(self, data: bytes) -> None:
        assert self.ep_out is not None
        chunk_size = 4096
        for i in range(0, len(data), chunk_size):
            self.usb_dev.bulk_write(self.ep_out, data[i : i + chunk_size], timeout=5000)

    def read(self, size: int, timeout_ms: int = 1000) -> bytes:
        assert self.ep_in is not None
        buf = bytearray()
        deadline = time.time() + (timeout_ms / 1000.0)
        while len(buf) < size and time.time() < deadline:
            remaining = timeout_ms - int((deadline - time.time()) * 1000)
            remaining = max(remaining, 50)
            chunk = self.usb_dev.bulk_read(self.ep_in, size - len(buf), timeout=remaining)
            if chunk:
                buf.extend(chunk)
            else:
                break
        return bytes(buf)

    def read_available(self, max_size: int = 4096, timeout_ms: int = 200) -> bytes:
        """Đọc bất kỳ dữ liệu nào sẵn có, không chờ đủ `max_size`."""
        assert self.ep_in is not None
        return self.usb_dev.bulk_read(self.ep_in, max_size, timeout=timeout_ms)

    def flush(self) -> None:
        """Xả (đọc và bỏ) dữ liệu còn sót lại trong buffer IN."""
        try:
            while self.read_available(max_size=4096, timeout_ms=50):
                pass
        except Exception:
            pass

    def close(self) -> None:
        pass

    # --- Reset ESP32 dùng DTR/RTS (giống "classic reset" của esptool) ---
    def hard_reset(self) -> None:
        self.set_dtr_rts(dtr=False, rts=True)
        time.sleep(0.1)
        self.set_dtr_rts(dtr=False, rts=False)

    def enter_bootloader(self) -> None:
        """
        Trình tự classic reset để đưa ESP32 vào chế độ download qua UART
        (EN nối RTS qua transistor đảo, GPIO0 nối DTR - board dev kit
        chuẩn kiểu NodeMCU/DevKitC).
        """
        self.set_dtr_rts(dtr=False, rts=True)   # EN = thấp (giữ reset)
        time.sleep(0.1)
        self.set_dtr_rts(dtr=True, rts=False)   # GPIO0 = thấp, EN = cao (thoát reset)
        time.sleep(0.05)
        self.set_dtr_rts(dtr=False, rts=False)  # thả GPIO0


# ==========================================================================
# Factory
# ==========================================================================


def _driver_classes():
    # Import trễ (lazy) để tránh vòng lặp import giữa các module driver.
    from cp210x import CP210xBridge
    from ch340 import CH340Bridge
    from ftdi import FT232Bridge
    from cdc_acm import CdcAcmBridge

    # Thứ tự: driver vendor-specific trước, CDC-ACM chuẩn (native USB
    # của ESP32-S2/S3/C3/C6/H2) là phương án cuối vì nó cũng có thể
    # khớp nhầm những thiết bị CDC-ACM chung chung khác.
    return [CP210xBridge, CH340Bridge, FT232Bridge, CdcAcmBridge]


def detect_driver(vendor_id: int, product_id: int) -> Optional[Type[UartBridge]]:
    for cls in _driver_classes():
        if cls.detect(vendor_id, product_id):
            return cls
    return None


def create_bridge(usb_dev: AndroidUsbDevice, vendor_id: int, product_id: int) -> UartBridge:
    cls = detect_driver(vendor_id, product_id)
    if cls is None:
        raise UartBridgeError(
            f"Khong ho tro chip USB-UART co VID={vendor_id:04x} PID={product_id:04x}. "
            "Cac driver duoc ho tro: CP210x, CH340/CH9102, FT232/FT231X, "
            "va CDC-ACM chuan (ESP32-S2/S3/C3/C6/H2 USB native)."
        )
    logger.debug(f"usb_bridge: chon driver {cls.NAME} cho VID={vendor_id:04x} PID={product_id:04x}")
    return cls(usb_dev)
