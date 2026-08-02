#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_helper.py
=============
Lớp trung gian giao tiếp với `termux-usb` (thuộc gói `termux-api`) để:

  1. Liệt kê các thiết bị USB đang cắm vào điện thoại (`termux-usb -l`).
  2. Xin quyền truy cập USB từ Android cho một thiết bị cụ thể
     (`termux-usb -r -e <lệnh> <đường_dẫn>`).
  3. Đọc Vendor ID / Product ID của thiết bị để nhận diện chip UART-USB
     (CP2102, CH340, CH9102, FT232, PL2303) — từ đó suy ra đây có khả
     năng là board ESP32/ESP8266 hay không.

QUAN TRỌNG — Vì sao KHÔNG dùng serial.tools.list_ports:
    Trên Android, không có quyền liệt kê /dev/ttyUSB* hay /dev/ttyACM*
    theo cách Linux desktop thường làm (sandbox của Android chặn truy
    cập trực tiếp vào /dev). Cách duy nhất được Google cho phép là đi
    qua Android USB Host API, và Termux expose API này qua lệnh
    `termux-usb`. Vì vậy toàn bộ luồng nhận diện thiết bị ở đây dựa
    100% vào `termux-usb`, tuyệt đối không import
    `serial.tools.list_ports`.

Cách `termux-usb -r -e` hoạt động:
    `termux-usb -r -e "python3 script.py arg1" /dev/bus/usb/001/002`
    sẽ:
      - Hiển thị hộp thoại xin quyền USB trên Android (nếu chưa cấp).
      - Sau khi được cấp quyền, THỰC THI lệnh được truyền cho `-e`,
        với đường dẫn thiết bị (/dev/bus/usb/001/002) được nối vào
        cuối dòng lệnh làm tham số cuối cùng.
      - Tiến trình con (được -e thực thi) lúc này có thể `os.open()`
        trực tiếp file đặc biệt đó vì quyền đã được Android cấp cho
        phiên làm việc hiện tại.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from utils import parse_json_safe  # noqa: E402

# VID:PID của các chip USB-UART phổ biến trên board ESP32/ESP8266.
KNOWN_USB_UART_CHIPS = {
    (0x10C4, 0xEA60): "CP2102 / CP2102N (Silicon Labs)",
    (0x1A86, 0x7523): "CH340 / CH340C (WCH)",
    (0x1A86, 0x55D4): "CH9102 (WCH)",
    (0x0403, 0x6001): "FT232 (FTDI)",
    (0x0403, 0x6015): "FT231X (FTDI)",
    (0x067B, 0x2303): "PL2303 (Prolific)",
    (0x303A, 0x1001): "ESP32-S2/S3 USB-Serial-JTAG (native)",
    (0x303A, 0x0002): "ESP32-C3 USB-CDC (native)",
}


class UsbHelperError(RuntimeError):
    """Lỗi liên quan đến thao tác USB qua termux-usb."""


@dataclass
class UsbDevice:
    path: str
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None

    @property
    def description(self) -> str:
        if self.vendor_id is not None and self.product_id is not None:
            key = (self.vendor_id, self.product_id)
            name = KNOWN_USB_UART_CHIPS.get(key, "Thiết bị USB không xác định")
            return f"{name} (VID={self.vendor_id:04x} PID={self.product_id:04x})"
        return "Thiết bị USB (chưa xác định chip)"

    @property
    def is_known_uart_chip(self) -> bool:
        if self.vendor_id is None or self.product_id is None:
            return False
        return (self.vendor_id, self.product_id) in KNOWN_USB_UART_CHIPS


def _ensure_termux_api() -> None:
    if shutil.which("termux-usb") is None:
        raise UsbHelperError(
            "Không tìm thấy lệnh 'termux-usb'. Hãy cài đặt gói termux-api:\n"
            "  pkg install termux-api\n"
            "và cài ứng dụng Termux:API từ F-Droid/Google Play."
        )


def list_usb_devices() -> List[UsbDevice]:
    """Trả về danh sách thiết bị USB đang cắm (chưa có VID/PID)."""
    _ensure_termux_api()
    try:
        result = subprocess.run(
            ["termux-usb", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise UsbHelperError("termux-usb -l bị timeout. Kiểm tra Termux:API đã cài chưa.") from exc

    if result.returncode != 0:
        raise UsbHelperError(f"termux-usb -l thất bại: {result.stderr.strip()}")

    data = parse_json_safe(result.stdout)
    if data is None or not isinstance(data, list):
        raise UsbHelperError(f"Không parse được kết quả termux-usb -l: {result.stdout!r}")

    return [UsbDevice(path=p) for p in data]


def read_device_descriptor(device_path: str, timeout: float = 15.0) -> Optional[UsbDevice]:
    """
    Xin quyền truy cập thiết bị và đọc VID/PID bằng cách thực thi một
    tiến trình con Python nội bộ (_descriptor_probe) sau khi quyền được
    Android cấp. Trả về None nếu người dùng từ chối cấp quyền hoặc lỗi.
    """
    _ensure_termux_api()
    probe_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_descriptor_probe.py")
    cmd = f"{sys.executable} {probe_script}"
    try:
        result = subprocess.run(
            ["termux-usb", "-r", "-e", cmd, device_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"Xin quyền USB cho {device_path} bị timeout (người dùng chưa xác nhận?)")
        return None

    data = parse_json_safe(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "")
    if not data:
        logger.debug(f"Không đọc được descriptor cho {device_path}: {result.stderr}")
        return UsbDevice(path=device_path)

    return UsbDevice(
        path=device_path,
        vendor_id=data.get("vendor_id"),
        product_id=data.get("product_id"),
    )


def request_permission_and_run(device_path: str, command: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    """
    Xin quyền truy cập thiết bị USB rồi thực thi `command` (nhận đường
    dẫn thiết bị làm tham số cuối cùng). Đây là hàm lõi được flash.sh,
    monitor.sh, chipinfo.sh, mac.sh gọi gián tiếp thông qua
    android_esptool.py.
    """
    _ensure_termux_api()
    logger.info("Đang chờ Android cấp quyền truy cập USB (kiểm tra thông báo trên màn hình)...")
    return subprocess.run(
        ["termux-usb", "-r", "-e", command, device_path],
        timeout=timeout,
    )


def find_esp32_candidates() -> List[UsbDevice]:
    """
    Liệt kê thiết bị USB, sau đó đọc descriptor từng thiết bị để lọc ra
    những thiết bị có VID/PID trùng với chip UART-USB đã biết.
    """
    devices = list_usb_devices()
    if not devices:
        raise UsbHelperError(
            "Không tìm thấy thiết bị USB nào. Hãy kiểm tra:\n"
            "  1. Cáp OTG đã cắm đúng chiều\n"
            "  2. Board ESP32 đã cắm vào cáp OTG\n"
            "  3. Điện thoại hỗ trợ USB Host (OTG)"
        )

    candidates: List[UsbDevice] = []
    for dev in devices:
        full = read_device_descriptor(dev.path)
        if full is not None:
            candidates.append(full)

    known = [d for d in candidates if d.is_known_uart_chip]
    return known if known else candidates


def choose_device(devices: List[UsbDevice]) -> UsbDevice:
    """Nếu có nhiều thiết bị, hiển thị menu để người dùng chọn."""
    if len(devices) == 1:
        print(f"Đã tìm thấy: {devices[0].description} tại {devices[0].path}", file=sys.stderr)
        return devices[0]

    print("\nTìm thấy nhiều thiết bị USB. Vui lòng chọn:\n", file=sys.stderr)
    for idx, dev in enumerate(devices, start=1):
        print(f"  {idx}. {dev.description}  ({dev.path})", file=sys.stderr)
    print(file=sys.stderr)

    while True:
        try:
            choice = input(f"Nhập số thứ tự [1-{len(devices)}]: ").strip()
            index = int(choice) - 1
            if 0 <= index < len(devices):
                return devices[index]
        except (ValueError, EOFError):
            pass
        print("Lựa chọn không hợp lệ, thử lại.", file=sys.stderr)
