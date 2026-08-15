#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CP210x USB-UART tối giản cho ESP32; không dùng pyserial."""

from __future__ import annotations
import struct
from usbdevfs import ioctl_control, bulk_read, bulk_write, claim_interface, USBError

VID = 0x10C4
PID = 0xEA60
EP_OUT = 0x01
EP_IN = 0x81

REQ_IFC_ENABLE = 0x00
REQ_SET_BAUDRATE = 0x1E
REQ_SET_LINE_CTL = 0x03
REQ_SET_MHS = 0x07
REQ_GET_MDMSTS = 0x08

CP210X_INTERFACE = 0
USB_REQ_HOST_TO_DEVICE = 0x41
USB_REQ_DEVICE_TO_HOST = 0xC1

IFC_ENABLE = 0x0001

# CP210x modem-control: bit 8/9 chọn DTR/RTS, bit 0/1 là trạng thái.
DTR = 0x0100
RTS = 0x0200
DTR_STATE = 0x0001
RTS_STATE = 0x0002
MHS_MASK = DTR | RTS

class CP210x:
    def __init__(self, fd: int, debug=False):
        self.fd = fd
        self.debug = debug

    def control_out(self, req, value=0, data=b""):
        return ioctl_control(self.fd, USB_REQ_HOST_TO_DEVICE, req, value,
                             CP210X_INTERFACE, data)

    def control_in(self, req, value=0, length=1):
        return ioctl_control(self.fd, USB_REQ_DEVICE_TO_HOST, req, value,
                             CP210X_INTERFACE, b"\x00"*length)

    def enable(self):
        self.control_out(REQ_IFC_ENABLE, IFC_ENABLE)

    def set_baudrate(self, baud: int):
        self.control_out(REQ_SET_BAUDRATE, 0, struct.pack("<I", baud))

    def set_line_8n1(self):
        # CP210x line control: 8 data bits, no parity, 1 stop bit.
        self.control_out(REQ_SET_LINE_CTL, 0x0800)

    def set_mhs(self, dtr: bool, rts: bool):
        state = (DTR_STATE if dtr else 0) | (RTS_STATE if rts else 0)
        self.control_out(REQ_SET_MHS, MHS_MASK | state)

    def modem_status(self) -> int:
        return self.control_in(REQ_GET_MDMSTS, length=1)[0]

    def configure(self, baud=115200):
        # Claim interface 0 trước khi dùng control/bulk transfer. termux-usb
        # không tự claim; nếu interface đã được claim từ trước (ví dụ do
        # kernel tự auto-claim ở lần chạy trước) thì bỏ qua lỗi, vì mục
        # tiêu chỉ là đảm bảo có quyền dùng interface, không phải claim mới.
        try:
            claim_interface(self.fd, CP210X_INTERFACE)
        except USBError as e:
            if self.debug: print(f"[CẢNH BÁO] Claim interface: {e}", flush=True)
        self.enable()
        self.set_baudrate(baud)
        self.set_line_8n1()
        # Trạng thái nhàn: cả DTR/RTS ở mức không kích hoạt.
        self.set_mhs(False, False)

    def bulk_write(self, data: bytes, timeout_ms=3000):
        total = 0
        while total < len(data):
            n = bulk_write(self.fd, EP_OUT, data[total:], timeout_ms)
            if n <= 0:
                raise USBError("USB Bulk OUT trả về 0 byte.")
            total += n
        if self.debug:
            print(f"USB BULK OUT: {total} byte | {data[:64].hex(' ')}", flush=True)
        return total

    def bulk_read(self, size=4096, timeout_ms=1000):
        data = bulk_read(self.fd, EP_IN, size, timeout_ms)
        if self.debug and data:
            print(f"USB BULK IN : {len(data)} byte | {data[:64].hex(' ')}", flush=True)
        return data
