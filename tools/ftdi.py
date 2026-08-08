#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ftdi.py
=======
Driver USB vendor-specific cho chip FTDI FT232R / FT231X - dùng trên
một số board ESP32 dev kit đời cũ / mạch nạp rời.

bmRequestType 0x40 (vendor, host->device, device/port).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usb_bridge import UartBridge  # noqa: E402
import logger  # noqa: E402

_KNOWN_VID_PID = {
    (0x0403, 0x6001),  # FT232R
    (0x0403, 0x6015),  # FT231X
}


class FT232Bridge(UartBridge):
    NAME = "FTDI"

    REQ_TYPE_OUT = 0x40
    RESET_REQUEST = 0x00
    SET_BAUDRATE_REQUEST = 0x03
    SET_DATA_REQUEST = 0x04
    MODEM_CTRL_REQUEST = 0x01

    FTDI_CLOCK = 3000000

    @classmethod
    def detect(cls, vendor_id: int, product_id: int) -> bool:
        return (vendor_id, product_id) in _KNOWN_VID_PID

    def open(self) -> None:
        self.usb_dev.claim_interface(self.interface)
        eps = self.usb_dev.find_bulk_endpoints(self.interface)
        self.ep_in, self.ep_out = eps.ep_in, eps.ep_out

        # Xoa STALL con sot lai tu phien truoc (xem giai thich chi tiet
        # trong cp210x.py) truoc khi bat dau doc/ghi.
        self.usb_dev.clear_endpoint_halt(self.ep_in)
        self.usb_dev.clear_endpoint_halt(self.ep_out)

        # SIO_RESET rồi cấu hình 8N1. Chỉ số "port" của FTDI thường là
        # interface + 1 theo quy ước firmware D2XX.
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.RESET_REQUEST, 0, self.interface + 1)
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.SET_DATA_REQUEST, 0x0008, self.interface + 1)
        logger.debug("FT232: da reset va cau hinh 8N1")

    def set_baud(self, baud: int) -> None:
        divisor = max(1, self.FTDI_CLOCK // baud)
        self.usb_dev.control_write(
            self.REQ_TYPE_OUT, self.SET_BAUDRATE_REQUEST, divisor & 0xFFFF, self.interface + 1
        )
        logger.debug(f"FT232: dat baudrate xap xi {baud} (divisor={divisor})")

    def _set_modem_lines(self, dtr: bool, rts: bool) -> None:
        value = 0x0000
        if dtr:
            value |= 0x0001
        value |= 0x0100  # bật mask DTR
        if rts:
            value |= 0x0002
        value |= 0x0200  # bật mask RTS
        self.usb_dev.control_write(self.REQ_TYPE_OUT, self.MODEM_CTRL_REQUEST, value, self.interface + 1)
        self._dtr, self._rts = dtr, rts
