#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb_raw.py
===================
Lớp giao tiếp USB mức thấp cho Android/Termux.

Vì Android không cho phép mở /dev/bus/usb/* trực tiếp nếu chưa được cấp
quyền qua Android USB Host API, luồng hoạt động là:

    1. usb_helper.request_permission_and_run() gọi `termux-usb -r -e`
       để Android hiển thị hộp thoại xin quyền và (sau khi được cấp)
       thực thi tiến trình con của chúng ta, truyền vào đường dẫn thiết
       bị (vd: /dev/bus/usb/001/002) làm tham số cuối cùng.
    2. Trong tiến trình con đó, ta `os.open(path, os.O_RDWR)` để lấy
       file descriptor — lúc này quyền đã được Android cấp cho phiên
       làm việc nên open() sẽ thành công.
    3. fd đó được "wrap" bằng thư viện `usb1` (Python binding cho
       libusb-1.0, gói pip: libusb1) thông qua
       `USBContext().wrapSysDevice(fd)` — API dành riêng cho các
       trường hợp fd đã được hệ điều hành cấp quyền sẵn (đúng chuẩn
       Android USB Host / Termux).

KHÔNG dùng serial.tools.list_ports, KHÔNG enumerate tty, KHÔNG cần
root.
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import usb1
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "Thiếu thư viện 'libusb1'. Cài bằng lệnh:\n"
        "  pkg install libusb clang\n"
        "  pip install libusb1\n"
    )
    raise

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402


class AndroidUsbError(RuntimeError):
    pass


@dataclass
class EndpointPair:
    ep_in: int
    ep_out: int
    max_packet_size: int = 64


class AndroidUsbDevice:
    """
    Bọc một thiết bị USB đã được cấp quyền, expose control transfer và
    bulk transfer để các lớp UART bridge (CP210x/CH340/...) sử dụng.
    """

    def __init__(self, device_path: str) -> None:
        self.device_path = device_path
        self._fd: Optional[int] = None
        self._context: Optional["usb1.USBContext"] = None
        self._handle: Optional["usb1.USBDeviceHandle"] = None
        self._claimed_interface: Optional[int] = None

    # ------------------------------------------------------------------
    def open(self) -> None:
        """Mở fd (đã được Android cấp quyền qua termux-usb) và wrap bằng libusb."""
        try:
            self._fd = os.open(self.device_path, os.O_RDWR)
        except OSError as exc:
            raise AndroidUsbError(
                f"Không mở được {self.device_path}: {exc}. "
                "Có thể quyền USB chưa được cấp hoặc thiết bị đã bị rút."
            ) from exc

        self._handle = self._wrap_with_retry()

        try:
            self._handle.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass  # không phải lỗi nghiêm trọng trên Android

    def _wrap_with_retry(self) -> "usb1.USBDeviceHandle":
        """Goi wrapSysDevice, tu dong fallback khi gap LIBUSB_ERROR_IO.

        LIBUSB_ERROR_IO tu wrapSysDevice() la CHAP CHON tren Android
        khong-root (phu thuoc trang thai phien quyen termux-usb da
        cap), khong chi xay ra voi mot kieu USBContext() cu the. Thu
        context tran truoc (uu tien vi cac module khac dung chung —
        chipinfo/mac/flash), neu fail thi thu lai 1 lan voi
        with_device_discovery=False truoc khi bao loi cho nguoi dung.
        """
        last_exc: Optional[usb1.USBError] = None
        for use_weak_authority in (False, True):
            try:
                context = usb1.USBContext(with_device_discovery=False) if use_weak_authority else usb1.USBContext()
            except TypeError:
                context = usb1.USBContext()
            except usb1.USBError:
                continue
            try:
                handle = context.wrapSysDevice(self._fd)
                self._context = context
                return handle
            except usb1.USBError as exc:
                last_exc = exc
                try:
                    context.close()
                except Exception:
                    pass
                logger.warning(
                    f"wrapSysDevice thất bại ({'weak-authority' if use_weak_authority else 'mặc định'}): {exc}"
                    + ("" if use_weak_authority else " — đang thử lại với with_device_discovery=False...")
                )
        raise AndroidUsbError(
            f"libusb wrapSysDevice thất bại ở cả 2 kiểu context: {last_exc}. "
            "Đây thường là lỗi tạm thời của phiên quyền termux-usb. Hãy thử: "
            "rút cắm lại dây USB, chạy lại lệnh, hoặc khởi động lại Termux "
            "nếu vẫn lỗi."
        ) from last_exc

    def claim_interface(self, interface: int = 0) -> None:
        assert self._handle is not None
        try:
            self._handle.claimInterface(interface)
            self._claimed_interface = interface
        except usb1.USBError as exc:
            raise AndroidUsbError(f"Không claim được interface {interface}: {exc}") from exc

    def find_bulk_endpoints(self, interface: int = 0) -> EndpointPair:
        """Duyệt configuration descriptor để tìm endpoint bulk IN/OUT."""
        assert self._handle is not None
        device = self._handle.getDevice()
        ep_in = ep_out = None
        max_packet = 64
        for cfg in device.iterConfigurations():
            for iface in cfg.iterInterfaces():
                for setting in iface.iterSettings():
                    if setting.getNumber() != interface:
                        continue
                    for ep in setting.iterEndpoints():
                        addr = ep.getAddress()
                        attrs = ep.getAttributes()
                        is_bulk = (attrs & 0x03) == 0x02
                        if not is_bulk:
                            continue
                        if addr & 0x80:
                            ep_in = addr
                        else:
                            ep_out = addr
                        max_packet = ep.getMaxPacketSize()
        if ep_in is None or ep_out is None:
            raise AndroidUsbError("Không tìm thấy endpoint bulk IN/OUT trên thiết bị.")
        return EndpointPair(ep_in=ep_in, ep_out=ep_out, max_packet_size=max_packet)

    # ------------------------------------------------------------------
    def control_write(self, request_type: int, request: int, value: int, index: int, data: bytes = b"", timeout: int = 3000) -> int:
        assert self._handle is not None
        return self._handle.controlWrite(request_type, request, value, index, data, timeout=timeout)

    def control_read(self, request_type: int, request: int, value: int, index: int, length: int, timeout: int = 3000) -> bytes:
        assert self._handle is not None
        return self._handle.controlRead(request_type, request, value, index, length, timeout=timeout)

    def bulk_write(self, endpoint: int, data: bytes, timeout: int = 3000) -> int:
        assert self._handle is not None
        return self._handle.bulkWrite(endpoint, data, timeout=timeout)

    def bulk_read(self, endpoint: int, length: int, timeout: int = 3000) -> bytes:
        assert self._handle is not None
        try:
            return self._handle.bulkRead(endpoint, length, timeout=timeout)
        except usb1.USBErrorTimeout as exc:
            # Xem giai thich chi tiet trong android_usb.py: khong duoc vut bo
            # exc.received, neu khong se lam dut/lech du lieu UART khi timeout
            # roi dung giua mot bulk transfer da nhan duoc mot phan.
            return bytes(getattr(exc, "received", b"") or b"")

    def get_device_descriptor(self) -> Tuple[int, int]:
        """Trả về (vendor_id, product_id) của thiết bị."""
        assert self._handle is not None
        device = self._handle.getDevice()
        return device.getVendorID(), device.getProductID()

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._handle is not None:
            try:
                if self._claimed_interface is not None:
                    self._handle.releaseInterface(self._claimed_interface)
            except Exception:
                pass
            try:
                self._handle.close()
            except Exception:
                pass
            self._handle = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "AndroidUsbDevice":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
