#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uart_bridge.py
===============
Triển khai giao thức USB vendor-specific cho các chip USB-UART thường
gặp trên board ESP32/ESP8266, thay thế hoàn toàn cho pySerial (vốn cần
tty node mà Android không cấp cho ứng dụng thường).

Mỗi lớp *Bridge cung cấp một giao diện thống nhất:

    open()                      - khởi tạo UART, bật interface
    set_baudrate(baud)          - đổi tốc độ baud
    set_dtr_rts(dtr, rts)       - điều khiển DTR/RTS (dùng để reset ESP32)
    write(data)                 - ghi bytes ra UART (qua bulk OUT)
    read(size, timeout)         - đọc bytes từ UART (qua bulk IN)
    close()                     - đóng interface

Giá trị thanh ghi/lệnh vendor được lấy từ tài liệu driver Linux nguồn mở
(cp210x.c, ch341.c) — đây là các giao thức USB công khai, không phải bí
mật thương mại.

Ghi chú phần cứng: một số board clone giá rẻ (đặc biệt CH340 đời cũ)
có thể lệch nhẹ so với datasheet gốc; nếu gặp lỗi giao tiếp, thử baud
rate khác hoặc board khác trước khi báo lỗi.
"""

from __future__ import annotations

import struct
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from android_usb_raw import AndroidUsbDevice, AndroidUsbError  # noqa: E402
import logger  # noqa: E402


class UartBridgeError(RuntimeError):
    pass


class UartBridge(ABC):
    """Giao diện chung cho mọi chip USB-UART."""

    def __init__(self, usb_dev: AndroidUsbDevice, interface: int = 0) -> None:
        self.usb_dev = usb_dev
        self.interface = interface
        self.ep_in: Optional[int] = None
        self.ep_out: Optional[int] = None
        self._dtr = False
        self._rts = False

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def set_baudrate(self, baud: int) -> None: ...

    @abstractmethod
    def set_dtr_rts(self, dtr: bool, rts: bool) -> None: ...

    def write(self, data: bytes) -> None:
        assert self.ep_out is not None
        # Chia nhỏ theo max packet size để tránh lỗi trên một số chip.
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

    def close(self) -> None:
        pass

    # --- Reset ESP32 dùng DTR/RTS (giống esptool "classic reset") -----
    def hard_reset(self) -> None:
        self.set_dtr_rts(dtr=False, rts=True)
        time.sleep(0.1)
        self.set_dtr_rts(dtr=False, rts=False)

    def enter_bootloader(self) -> None:
        """
        Trình tự classic reset của esptool để đưa ESP32 vào chế độ
        download qua UART (EN nối RTS qua transistor đảo, GPIO0 nối DTR).
        """
        self.set_dtr_rts(dtr=False, rts=True)   # EN = thấp (giữ reset)
        time.sleep(0.1)
        self.set_dtr_rts(dtr=True, rts=False)   # GPIO0 = thấp, EN = cao (thoát reset)
        time.sleep(0.05)
        self.set_dtr_rts(dtr=False, rts=False)  # thả GPIO0


# ==========================================================================
# CP2102 / CP2102N (Silicon Labs) — bmRequestType 0x41 (vendor, host->device, interface)
# ==========================================================================


class CP210xBridge(UartBridge):
    IFC_ENABLE = 0x00
    SET_BAUDRATE = 0x1E
    SET_LINE_CTL = 0x03
    SET_MHS = 0x07

    REQ_TYPE_OUT = 0x41

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out

        # Bật interface UART.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.IFC_ENABLE, 1, self.interface)
        # 8N1.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_LINE_CTL, 0x0800, self.interface)
        logger.debug("CP210x: đã bật interface UART (8N1)")

    def set_baudrate(self, baud: int) -> None:
        data = struct.pack("<I", baud)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_BAUDRATE, 0, self.interface, data)
        logger.debug(f"CP210x: đặt baudrate = {baud}")

    def set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        # bit0=DTR state, bit1=RTS state, bit8=DTR mask, bit9=RTS mask.
        value = 0x0300  # bật mask điều khiển cả DTR và RTS
        if dtr:
            value |= 0x0001
        if rts:
            value |= 0x0002
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_MHS, value, self.interface)
        self._dtr, self._rts = dtr, rts

    def close(self) -> None:
        try:
            self.usb_dev.control_write(self.REQ_TYPE_OUT, self.IFC_ENABLE, 0, self.interface)
        except Exception:
            pass


# ==========================================================================
# CH340 / CH340C / CH9102 (WCH) — bmRequestType 0x40 (vendor, host->device, device)
# ==========================================================================


class CH340Bridge(UartBridge):
    REQ_TYPE_OUT = 0x40
    REQ_TYPE_IN = 0xC0

    REQ_WRITE_REG = 0x9A
    REQ_READ_REG = 0x95
    REQ_MODEM_CTRL = 0xA4
    REQ_SERIAL_INIT = 0xA1

    BIT_DTR = 0x20
    BIT_RTS = 0x40

    BAUDBASE_FACTOR = 1532620800
    BAUDBASE_DIVMAX = 3

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out

        # Đọc 2 thanh ghi trạng thái ban đầu (giống hành vi driver Linux,
        # một số clone CH340 yêu cầu bước đọc này trước khi init).
        try:
            self.usb_dev.control_read(self.REQ_TYPE_IN, self.REQ_READ_REG, 0x2518, 0, 2)
        except Exception:
            pass

        # Khởi tạo serial: giá trị mặc định 9600-8N1, sẽ set lại baud sau.
        self._write_lcr(0x00)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_SERIAL_INIT, 0x9C, 0x0000)
        logger.debug("CH340: đã khởi tạo UART")

    def _write_lcr(self, lcr: int) -> None:
        # 8N1 = 0xC3 (8 data bit | không parity | 1 stop bit theo bảng CH34x)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x2518, 0x0050 | lcr)

    def set_baudrate(self, baud: int) -> None:
        factor = self.BAUDBASE_FACTOR // baud
        divisor = self.BAUDBASE_DIVMAX
        while factor > 0xFFF0 and divisor > 0:
            factor >>= 3
            divisor -= 1
        if factor > 0xFFF0:
            raise UartBridgeError(f"Baudrate {baud} không hỗ trợ trên CH340")
        factor = 0x10000 - factor
        a = (factor & 0xFF00) | divisor
        b = factor & 0xFF
        value = a | 0x80
        index = (b << 8) | 0x0D
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x1312, value)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x0F2C, index)
        logger.debug(f"CH340: đặt baudrate = {baud} (factor={factor:#x} divisor={divisor})")

    def set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        control = 0
        if dtr:
            control |= self.BIT_DTR
        if rts:
            control |= self.BIT_RTS
        value = (~control) & 0xFF
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_MODEM_CTRL, value, 0)
        self._dtr, self._rts = dtr, rts


# ==========================================================================
# FT232 / FT231X (FTDI) — bmRequestType 0x40 (vendor, host->device, device)
# ==========================================================================


class FT232Bridge(UartBridge):
    REQ_TYPE_OUT = 0x40
    RESET_REQUEST = 0x00
    SET_BAUDRATE_REQUEST = 0x03
    SET_DATA_REQUEST = 0x04
    MODEM_CTRL_REQUEST = 0x01

    FTDI_CLOCK = 3000000

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out
        # Reset toàn bộ (SIO_RESET) rồi 8N1.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.RESET_REQUEST, 0, self.interface + 1)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_DATA_REQUEST, 0x0008, self.interface + 1)
        logger.debug("FT232: đã reset và cấu hình 8N1")

    def set_baudrate(self, baud: int) -> None:
        divisor = max(1, self.FTDI_CLOCK // baud)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_BAUDRATE_REQUEST, divisor & 0xFFFF, self.interface + 1)
        logger.debug(f"FT232: đặt baudrate xấp xỉ {baud} (divisor={divisor})")

    def set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        value = 0x0000
        if dtr:
            value |= 0x0001
        if rts:
            value |= 0x0002
        value |= 0x0100 if True else 0  # bật mask DTR
        value |= 0x0200  # bật mask RTS
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.MODEM_CTRL_REQUEST, value, self.interface + 1)
        self._dtr, self._rts = dtr, rts


# ==========================================================================
# PL2303 (Prolific) — bmRequestType 0x21 (class, host->device, interface)
# ==========================================================================


class PL2303Bridge(UartBridge):
    REQ_TYPE_OUT = 0x21
    SET_LINE_REQUEST = 0x20
    SET_CONTROL_REQUEST = 0x22

    CTRL_DTR = 0x01
    CTRL_RTS = 0x02

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out
        self._send_line_coding(115200)
        logger.debug("PL2303: đã khởi tạo UART")

    def _send_line_coding(self, baud: int) -> None:
        # 7 byte: baud(4, LE) + stop_bits(1) + parity(1) + data_bits(1)
        data = struct.pack("<IBBB", baud, 0, 0, 8)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_LINE_REQUEST, 0, self.interface, data)

    def set_baudrate(self, baud: int) -> None:
        self._send_line_coding(baud)
        logger.debug(f"PL2303: đặt baudrate = {baud}")

    def set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        value = 0
        if dtr:
            value |= self.CTRL_DTR
        if rts:
            value |= self.CTRL_RTS
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_CONTROL_REQUEST, value, self.interface)
        self._dtr, self._rts = dtr, rts


# ==========================================================================
# Factory
# ==========================================================================

_BRIDGE_BY_VID_PID = {
    (0x10C4, 0xEA60): CP210xBridge,
    (0x1A86, 0x7523): CH340Bridge,
    (0x1A86, 0x55D4): CH340Bridge,  # CH9102 dùng chung giao thức cơ bản với CH340
    (0x0403, 0x6001): FT232Bridge,
    (0x0403, 0x6015): FT232Bridge,
    (0x067B, 0x2303): PL2303Bridge,
}


def create_bridge(usb_dev: AndroidUsbDevice, vendor_id: int, product_id: int) -> UartBridge:
    cls = _BRIDGE_BY_VID_PID.get((vendor_id, product_id))
    if cls is None:
        raise UartBridgeError(
            f"Không hỗ trợ chip USB-UART có VID={vendor_id:04x} PID={product_id:04x}. "
            "Các chip được hỗ trợ: CP2102, CH340, CH9102, FT232, FT231X, PL2303."
        )
    return cls(usb_dev)
