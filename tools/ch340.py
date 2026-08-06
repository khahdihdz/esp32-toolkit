#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ch340.py
========
Driver USB vendor-specific cho chip WCH CH340 / CH340C / CH9102 - phổ
biến trên board ESP32 clone giá rẻ / NodeMCU.

bmRequestType 0x40 (vendor, host->device, device) / 0xC0 (device->host).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usb_bridge import UartBridge, UartBridgeError  # noqa: E402
import logger  # noqa: E402

_KNOWN_VID_PID = {
    (0x1A86, 0x7523),  # CH340 / CH340C
    (0x1A86, 0x55D4),  # CH9102
}


class CH340Bridge(UartBridge):
    NAME = "CH340"

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

    @classmethod
    def detect(cls, vendor_id: int, product_id: int) -> bool:
        return (vendor_id, product_id) in _KNOWN_VID_PID

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out

        # Đọc 2 thanh ghi trạng thái ban đầu — hành vi giống driver
        # Linux, một số clone CH340 cần bước đọc này trước khi init.
        try:
            self.usb_dev.control_read(self.REQ_TYPE_IN, self.REQ_READ_REG, 0x2518, 0, 2)
        except Exception:
            pass

        self._write_lcr(0x00)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_SERIAL_INIT, 0x9C, 0x0000)
        logger.debug("CH340: da khoi tao UART")

    def _write_lcr(self, lcr: int) -> None:
        # 8N1 theo bảng thanh ghi CH34x.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x2518, 0x0050 | lcr)

    def set_baud(self, baud: int) -> None:
        factor = self.BAUDBASE_FACTOR // baud
        divisor = self.BAUDBASE_DIVMAX
        while factor > 0xFFF0 and divisor > 0:
            factor >>= 3
            divisor -= 1
        if factor > 0xFFF0:
            raise UartBridgeError(f"Baudrate {baud} khong ho tro tren CH340")
        factor = 0x10000 - factor
        a = (factor & 0xFF00) | divisor
        b = factor & 0xFF
        value = a | 0x80
        index = (b << 8) | 0x0D
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x1312, value)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_WRITE_REG, 0x0F2C, index)
        logger.debug(f"CH340: dat baudrate = {baud} (factor={factor:#x} divisor={divisor})")

    def _set_modem_lines(self, dtr: bool, rts: bool) -> None:
        control = 0
        if dtr:
            control |= self.BIT_DTR
        if rts:
            control |= self.BIT_RTS
        value = (~control) & 0xFF
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.REQ_MODEM_CTRL, value, 0)
        self._dtr, self._rts = dtr, rts
