#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb.py
==============
Lớp giao tiếp USB mức thấp cho Android/Termux, dựa 100% trên Android
USB Host API thông qua `termux-usb` + `libusb1`. KHÔNG dùng
serial.tools.list_ports, KHÔNG enumerate /dev/ttyUSB*, KHÔNG cần root.

Luồng hoạt động:
    1. `termux-usb -l` liệt kê các đường dẫn thiết bị đang cắm
       (KHÔNG cần cấp quyền, chỉ enumerate).
    2. `termux-usb -r -e <lệnh> <đường_dẫn>` xin quyền Android cho một
       thiết bị cụ thể; sau khi được cấp, THỰC THI <lệnh> với đường
       dẫn thiết bị làm tham số cuối cùng.
    3. Trong tiến trình con đó, AndroidUsbDevice.open() gọi
       `os.open(path, os.O_RDWR)` — lúc này quyền đã được cấp cho
       phiên hiện tại nên open() thành công.
    4. fd được "wrap" bằng `usb1.USBContext().wrapSysDevice(fd)` (API
       dành riêng cho fd đã được hệ điều hành cấp quyền sẵn — đúng
       chuẩn Android USB Host / Termux).

QUAN TRỌNG: toàn bộ luồng thao tác thật sự với thiết bị (mở, claim
interface, chuyển đổi driver UART, chạy giao thức ESP ROM loader...)
PHẢI diễn ra bên trong CÙNG MỘT phiên quyền `termux-usb -r -e` duy
nhất. Không được xin quyền một lần để "dò" thiết bị rồi xin quyền lần
nữa để thao tác — đó là nguyên nhân gây lỗi Permission denied ngắt
quãng ở kiến trúc cũ.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple


def _preload_termux_libusb() -> None:
    """Nạp trước file .so thật của libusb-1.0 trên Termux.

    `pip install libusb1` chỉ cài binding Python (ctypes wrapper) — nó
    KHÔNG chứa thư viện native libusb-1.0.so. Thư viện native đến từ
    gói Termux `pkg install libusb`, được cài vào $PREFIX/lib. Vấn đề
    là usb1._libusb1.loadLibrary() chỉ gọi ctypes.CDLL("libusb-1.0.so.0")
    bằng TÊN TRẦN (bare name), và trên Android không có ldconfig/cache
    hệ thống nên dlopen-by-name có thể không tìm ra file trong
    $PREFIX/lib dù file tồn tại — dẫn đến FileNotFoundError ngay cả
    khi đã "pkg install libusb" thành công.
    Giải pháp: chủ động ctypes.CDLL() bằng ĐƯỜNG DẪN ĐẦY ĐỦ trước khi
    usb1 tự load. Linker sẽ cache thư viện đã nạp theo soname, nên khi
    usb1 gọi lại bằng tên trần, nó sẽ dùng lại bản đã nạp thay vì tìm
    lại từ đầu.
    """
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    candidates = [
        f"{prefix}/lib/libusb-1.0.so.0",
        f"{prefix}/lib/libusb-1.0.so",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
            return


_preload_termux_libusb()

try:
    import usb1
except (ImportError, OSError) as exc:  # pragma: no cover
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    sys.stderr.write(
        f"Khong tai duoc thu vien 'libusb1'/'libusb-1.0.so': {exc}\n"
        "Kiem tra va cai lai:\n"
        "  pkg install libusb clang\n"
        "  pip install --force-reinstall libusb1 --break-system-packages\n"
        f"  ls {prefix}/lib/libusb-1.0.so*   # phai thay file ton tai\n"
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


@dataclass
class BulkInterface:
    interface: int
    ep_in: int
    ep_out: int
    max_packet_size: int = 64
    device_class: int = 0


class AndroidUsbDevice:
    """
    Bọc một thiết bị USB đã được Android cấp quyền (qua termux-usb),
    expose control transfer và bulk transfer cho các lớp UART bridge
    (cp210x/ch340/ftdi/cdc_acm) sử dụng.
    """

    def __init__(self, device_path: str) -> None:
        self.device_path = device_path
        self._fd: Optional[int] = None
        self._context: Optional["usb1.USBContext"] = None
        self._handle: Optional["usb1.USBDeviceHandle"] = None
        self._claimed_interfaces: List[int] = []

    # ------------------------------------------------------------------
    def open(self) -> None:
        """Mở fd (đã được Android cấp quyền qua termux-usb) và wrap bằng libusb.

        QUAN TRỌNG: `termux-usb -r -e <command> <device>` KHÔNG truyền lại
        đường dẫn thiết bị cho <command> — nó truyền một file descriptor
        SỐ NGUYÊN đã được mở sẵn (vd: "7"), kế thừa trực tiếp vào tiến
        trình con. Gọi os.open() trên chuỗi số đó sẽ luôn thất bại với
        "No such file or directory" vì không tồn tại file nào tên là "7".
        Do đó: nếu device_path toàn số, dùng thẳng làm fd; nếu là đường
        dẫn thật (vd: dùng ngoài luồng termux-usb -e, hoặc để debug thủ
        công), mới gọi os.open().
        """
        if self.device_path.isdigit():
            self._fd = int(self.device_path)
        else:
            try:
                self._fd = os.open(self.device_path, os.O_RDWR)
            except OSError as exc:
                raise AndroidUsbError(
                    f"Khong mo duoc {self.device_path}: {exc}. "
                    "Quyen USB co the chua duoc cap, hoac thiet bi da bi rut ra."
                ) from exc

        self._context = self._make_context()

        try:
            self._handle = self._context.wrapSysDevice(self._fd)
        except usb1.USBError as exc:
            raise AndroidUsbError(f"libusb wrapSysDevice that bai: {exc}") from exc

        try:
            self._handle.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass  # không nghiêm trọng trên Android (thường không có kernel driver)

    @staticmethod
    def _make_context() -> "usb1.USBContext":
        """Tao USBContext, tat device discovery neu thu vien ho tro.

        Tren Android khong root, libusb_wrap_sys_device() that bai voi
        LIBUSB_ERROR_IO neu context con co gang quet /sys/bus/usb luc
        khoi tao — vi tien trinh khong co quyen doc sysfs truc tiep, chi
        co fd da duoc Android cap qua termux-usb. Cac ban libusb cu dung
        LIBUSB_OPTION_WEAK_AUTHORITY de tat kiem tra nay; python-libusb1
        hien dai (libusb >= 1.0.27) thay bang tham so with_device_discovery.
        """
        try:
            return usb1.USBContext(with_device_discovery=False)
        except TypeError:
            # Ban usb1 cu hon khong ho tro tham so nay.
            return usb1.USBContext()
        except usb1.USBError:
            # libusb < 1.0.27: tham so duoc chap nhan nhung context init
            # that bai vi backend chua ho tro. Quay lai mac dinh.
            return usb1.USBContext()

    def claim_interface(self, interface: int) -> None:
        assert self._handle is not None
        if interface in self._claimed_interfaces:
            return
        try:
            self._handle.claimInterface(interface)
            self._claimed_interfaces.append(interface)
        except usb1.USBError as exc:
            raise AndroidUsbError(f"Khong claim duoc interface {interface}: {exc}") from exc

    def try_claim_interface(self, interface: int) -> bool:
        """Giống claim_interface nhưng không raise, trả về False nếu thất bại."""
        try:
            self.claim_interface(interface)
            return True
        except AndroidUsbError:
            return False

    def find_bulk_endpoints(self, interface: int) -> EndpointPair:
        """Duyệt configuration descriptor để tìm endpoint bulk IN/OUT của 1 interface cụ thể."""
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
                        if (attrs & 0x03) != 0x02:  # chỉ lấy bulk
                            continue
                        if addr & 0x80:
                            ep_in = addr
                        else:
                            ep_out = addr
                        max_packet = ep.getMaxPacketSize()
        if ep_in is None or ep_out is None:
            raise AndroidUsbError(f"Khong tim thay endpoint bulk IN/OUT tren interface {interface}.")
        return EndpointPair(ep_in=ep_in, ep_out=ep_out, max_packet_size=max_packet)

    def find_all_bulk_interfaces(self) -> List[BulkInterface]:
        """
        Duyệt toàn bộ interface của thiết bị, trả về danh sách interface
        có endpoint bulk IN+OUT (dùng cho thiết bị CDC-ACM có nhiều
        interface, vd: interface 0 = control (Class 0x02), interface 1
        = data (Class 0x0A) mang bulk endpoint thật sự).
        """
        assert self._handle is not None
        device = self._handle.getDevice()
        results: List[BulkInterface] = []
        for cfg in device.iterConfigurations():
            for iface in cfg.iterInterfaces():
                for setting in iface.iterSettings():
                    ep_in = ep_out = None
                    max_packet = 64
                    for ep in setting.iterEndpoints():
                        addr = ep.getAddress()
                        attrs = ep.getAttributes()
                        if (attrs & 0x03) != 0x02:
                            continue
                        if addr & 0x80:
                            ep_in = addr
                        else:
                            ep_out = addr
                        max_packet = ep.getMaxPacketSize()
                    if ep_in is not None and ep_out is not None:
                        results.append(
                            BulkInterface(
                                interface=setting.getNumber(),
                                ep_in=ep_in,
                                ep_out=ep_out,
                                max_packet_size=max_packet,
                                device_class=setting.getClass(),
                            )
                        )
        return results

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
        except usb1.USBErrorTimeout:
            return b""
        except usb1.USBErrorPipe:
            # Một số driver clone trả STALL khi buffer rỗng; bỏ qua như timeout.
            return b""

    def get_device_descriptor(self) -> Tuple[int, int]:
        """Trả về (vendor_id, product_id) của thiết bị."""
        assert self._handle is not None
        device = self._handle.getDevice()
        return device.getVendorID(), device.getProductID()

    def reset_device(self) -> None:
        assert self._handle is not None
        try:
            self._handle.resetDevice()
        except usb1.USBError:
            pass

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._handle is not None:
            for iface in list(self._claimed_interfaces):
                try:
                    self._handle.releaseInterface(iface)
                except Exception:
                    pass
            self._claimed_interfaces.clear()
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
