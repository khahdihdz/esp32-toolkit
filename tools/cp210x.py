#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cp210x.py
=========
Driver USB vendor-specific cho chip Silicon Labs CP2102 / CP2102N /
CP2105 - phổ biến trên board ESP32 DevKit V1, NodeMCU-32S, ...

bmRequestType 0x41 (vendor, host->device, interface).
"""

from __future__ import annotations

import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usb_bridge import UartBridge  # noqa: E402
import logger  # noqa: E402

_KNOWN_VID_PID = {
    (0x10C4, 0xEA60),  # CP2102 / CP2102N
    (0x10C4, 0xEA70),  # CP2105
}


class CP210xBridge(UartBridge):
    NAME = "CP210x"

    IFC_ENABLE = 0x00
    SET_BAUDRATE = 0x1E
    SET_LINE_CTL = 0x03
    SET_MHS = 0x07

    REQ_TYPE_OUT = 0x41

    @classmethod
    def detect(cls, vendor_id: int, product_id: int) -> bool:
        return (vendor_id, product_id) in _KNOWN_VID_PID

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out

        # Bật interface UART, cấu hình 8N1.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.IFC_ENABLE, 1, self.interface)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_LINE_CTL, 0x0800, self.interface)
        logger.debug("CP210x: da bat interface UART (8N1)")

    def set_baud(self, baud: int) -> None:
        data = struct.pack("<I", baud)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_BAUDRATE, 0, self.interface, data)
        logger.debug(f"CP210x: dat baudrate = {baud}")

    def _set_modem_lines(self, dtr: bool, rts: bool) -> None:
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
