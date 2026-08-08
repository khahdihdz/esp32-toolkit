#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdc_acm.py
==========
Driver USB CDC-ACM chuẩn (USB-IF class 0x02/0x0A), dùng cho các chip
ESP32 đời mới có cổng USB native đóng vai trò UART-over-USB trực tiếp
(không qua chip rời CP210x/CH340/FTDI):

    - ESP32-S2 / ESP32-S3: USB-Serial-JTAG hoặc USB-CDC (tuỳ firmware)
    - ESP32-C3 / ESP32-C6 / ESP32-H2: USB-Serial-JTAG

VID mặc định của Espressif cho các cổng native này là 0x303A. Vì đây
là thiết bị tuân theo chuẩn USB CDC-ACM công khai (không phải giao
thức vendor riêng), driver này cũng hoạt động như một fallback hợp lý
cho các board USB-to-serial CDC-ACM chuẩn khác nếu VID/PID không nằm
trong danh sách của cp210x/ch340/ftdi.

bmRequestType 0x21 (class, host->device, interface) gửi tới INTERFACE
ĐIỀU KHIỂN (control interface, Class 0x02 Communication). Endpoint
bulk IN/OUT nằm trên INTERFACE DỮ LIỆU (data interface, Class 0x0A),
thường là interface kế tiếp control interface.
"""

from __future__ import annotations

import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usb_bridge import UartBridge, UartBridgeError  # noqa: E402
import logger  # noqa: E402

ESPRESSIF_VID = 0x303A

# PID cụ thể coi là "biết chắc" là ESP32 native USB. Ngoài ra mọi PID
# khác của VID Espressif cũng được thử bằng driver này (native USB
# JTAG/Serial của các chip đời mới thường đổi PID theo revision).
_KNOWN_PID = {0x1001, 0x0002, 0x0009, 0x1002}

USB_CLASS_CDC_DATA = 0x0A

CDC_SET_LINE_CODING = 0x20
CDC_SET_CONTROL_LINE_STATE = 0x22

REQ_TYPE_CLASS_INTERFACE_OUT = 0x21


class CdcAcmBridge(UartBridge):
    NAME = "CDC-ACM"

    @classmethod
    def detect(cls, vendor_id: int, product_id: int) -> bool:
        if vendor_id != ESPRESSIF_VID:
            return False
        # Chấp nhận mọi PID của Espressif: native USB PID có thể khác
        # nhau theo chip/revision nhưng luôn nói giao thức CDC-ACM chuẩn.
        return True

    def open(self) -> None:
        bulk_ifaces = self.usb_dev.find_all_bulk_interfaces()
        if not bulk_ifaces:
            raise UartBridgeError("CDC-ACM: khong tim thay interface nao co endpoint bulk IN/OUT.")

        # Ưu tiên interface khai báo đúng class CDC-Data (0x0A).
        data_iface = next((i for i in bulk_ifaces if i.device_class == USB_CLASS_CDC_DATA), bulk_ifaces[0])

        self.interface = data_iface.interface
        self.ep_in, self.ep_out = data_iface.ep_in, data_iface.ep_out

        # Interface điều khiển (nhận lệnh class SET_LINE_CODING /
        # SET_CONTROL_LINE_STATE) thường là interface ngay trước data
        # interface trong descriptor CDC chuẩn.
        self._control_interface = max(0, data_iface.interface - 1)

        self.usb_dev.claim_interface(self.interface)
        # Claim thêm control interface nếu khác — không bắt buộc phải
        # thành công (một số thiết bị gộp control vào cùng interface).
        if self._control_interface != self.interface:
            self.usb_dev.try_claim_interface(self._control_interface)

        # Xoa STALL con sot lai tu phien truoc (xem giai thich chi tiet
        # trong cp210x.py) truoc khi bat dau doc/ghi.
        self.usb_dev.clear_endpoint_halt(self.ep_in)
        self.usb_dev.clear_endpoint_halt(self.ep_out)

        # Bật DTR+RTS mặc định (một số firmware ESP32-S3 USB-CDC chỉ
        # xuất dữ liệu ra cổng khi DTR được set).
        self._set_modem_lines(dtr=True, rts=True)
        logger.debug(
            f"CDC-ACM: data_if={self.interface} control_if={self._control_interface} "
            f"ep_in={self.ep_in:#x} ep_out={self.ep_out:#x}"
        )

    def set_baud(self, baud: int) -> None:
        # SET_LINE_CODING: 7 byte = baud(4, LE) + stop_bits(1) + parity(1) + data_bits(1)
        # stop_bits=0 (1 stop bit), parity=0 (none), data_bits=8.
        data = struct.pack("<IBBB", baud, 0, 0, 8)
        self.usb_dev.control_write(
            REQ_TYPE_CLASS_INTERFACE_OUT, CDC_SET_LINE_CODING, 0, self._control_interface, data
        )
        logger.debug(f"CDC-ACM: dat baudrate = {baud}")

    def _set_modem_lines(self, dtr: bool, rts: bool) -> None:
        value = 0
        if dtr:
            value |= 0x01
        if rts:
            value |= 0x02
        self.usb_dev.control_write(
            REQ_TYPE_CLASS_INTERFACE_OUT, CDC_SET_CONTROL_LINE_STATE, value, self._control_interface
        )
        self._dtr, self._rts = dtr, rts

    def enter_bootloader(self) -> None:
        """
        Trên chip có USB-Serial-JTAG native (ESP32-S3/C3/C6/H2), việc
        vào chế độ download qua toggling DTR/RTS thường KHÔNG cần thiết
        vì bản thân cổng USB-Serial-JTAG có thể tự động kích hoạt reset
        khi ROM loader nhận diện tín hiệu SLIP đặc biệt. Tuy vậy để
        tương thích ngược với board dùng auto-reset kiểu cổ điển (RTS/
        DTR nối EN/GPIO0 qua mạch rời), vẫn thực hiện trình tự reset
        chuẩn — không gây hại nếu board không đấu nối hai chân này.
        """
        super().enter_bootloader()

    def hard_reset(self) -> None:
        """
        LOI DA TUNG XAY RA O DAY: hard_reset() cua lop cha (dung chung
        cho CP2102/CH340/FTDI) ket thuc voi dtr=False vinh vien. Voi cac
        chip roi do, DTR chi la tin hieu dieu khien GPIO0 nen khong sao.
        Nhung voi CDC-ACM native (xem ghi chu o open() ben tren), mot so
        firmware ESP32-S3/C3 CHI xuat du lieu qua cong USB khi DTR=True
        - neu DTR bi bo lai False sau reset, thiet bi im lang TUYET DOI
        vinh vien du firmware van chay binh thuong ben trong, va bam nut
        RESET vat ly KHONG sua duoc vi DTR la trang thai phia host.
        Do do o day PHAI bat lai DTR=True ngay sau khi reset xong.
        """
        super().hard_reset()
        self._set_modem_lines(dtr=True, rts=False)
