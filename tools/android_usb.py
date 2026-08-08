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

        self._handle = self._wrap_with_retry()

        try:
            self._handle.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass  # không nghiêm trọng trên Android (thường không có kernel driver)

    def _wrap_with_retry(self) -> "usb1.USBDeviceHandle":
        """Goi wrapSysDevice, tu dong fallback khi gap LIBUSB_ERROR_IO.

        GHI CHU QUAN TRONG (2 lan sua doi, xem lich su):
        1) Ban dau: _make_context() uu tien with_device_discovery=False
           de ne LIBUSB_ERROR_IO. Nhung co nay chi giup wrapSysDevice,
           lai lam bulkRead() im lang vi libusb khong nap dung active
           config descriptor.
        2) Sau do: doi lai thanh USBContext() tran (giong
           android_usb_raw.py). Nhung thuc te hien truong cho thay
           LIBUSB_ERROR_IO tu wrapSysDevice() la CHAP CHON — no cung
           xay ra ca voi context tran (chipinfo.sh dung
           android_usb_raw.py, context tran, van bi LIBUSB_ERROR_IO).
           => Loi nay khong tat dinh theo co discovery, ma phu thuoc
           thoi diem/trang thai phien quyen termux-usb da cap.
        Giai phap cuoi: thu context tran truoc (uu tien vi bulk read on
        dinh hon). Neu wrapSysDevice bao IO error, dong context cu va
        thu lai DUY NHAT MOT LAN voi with_device_discovery=False truoc
        khi bo cuoc. Neu ca hai deu fail, bao loi ro cho nguoi dung biet
        day la loi tam thoi cua phien USB (thu rut cam lai thiet bi hoac
        chay lai lenh).
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
                    f"wrapSysDevice that bai ({'weak-authority' if use_weak_authority else 'mac dinh'}): {exc}"
                    + ("" if use_weak_authority else " — dang thu lai voi with_device_discovery=False...")
                )
        raise AndroidUsbError(
            f"libusb wrapSysDevice that bai o ca 2 kieu context: {last_exc}. "
            "Day thuong la loi tam thoi cua phien quyen termux-usb (Android "
            "chua san sang hoac thiet bi dang bi tien trinh khac giu). Hay thu: "
            "rut cam lai day USB, chay lai lenh, hoac neu van loi thi khoi dong "
            "lai Termux."
        ) from last_exc

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

    def clear_endpoint_halt(self, endpoint: int) -> None:
        """Chu dong CLEAR_FEATURE(ENDPOINT_HALT) cho mot endpoint.

        Goi phong ngua ngay sau khi claim interface, TRUOC KHI bat dau
        doc/ghi: trang thai STALL cua mot endpoint la trang thai CUA
        THIET BI (khong phai cua tien trinh/libusb), nen no co the con
        sot lai tu lan chay truoc bi crash/kill giua chung, hoac tu
        tien trinh Android USB Host truoc do. Bo qua loi vi hau het
        thiet bi se bao "khong co gi de clear" (khong nghiem trong).
        """
        assert self._handle is not None
        try:
            self._handle.clearHalt(endpoint)
        except usb1.USBError:
            pass

    def bulk_write(self, endpoint: int, data: bytes, timeout: int = 3000) -> int:
        assert self._handle is not None
        return self._handle.bulkWrite(endpoint, data, timeout=timeout)

    def bulk_read(self, endpoint: int, length: int, timeout: int = 3000) -> bytes:
        assert self._handle is not None
        try:
            return self._handle.bulkRead(endpoint, length, timeout=timeout)
        except usb1.USBErrorTimeout as exc:
            # QUAN TRONG: timeout co the xay ra GIUA CHUNG mot bulk transfer,
            # sau khi mot phan du lieu da thuc su den noi. libusb1 dinh kem
            # phan da nhan duoc vao exc.received - neu chi return b"" o day,
            # ta AM THAM VUT BO nhung byte hop le do, lam dut/lech dong du
            # lieu UART va khien cac dong log sau bi doc sai ("nghi ngo sai
            # baudrate") du firmware khong he loi.
            return bytes(getattr(exc, "received", b"") or b"")
        except usb1.USBErrorPipe:
            # SUA LOI QUAN TRONG: USBErrorPipe nghia la endpoint dang o
            # trang thai STALL (CLEAR_FEATURE/ENDPOINT_HALT chua duoc goi),
            # KHONG PHAI "khong co du lieu". Ban cu o day return b"" giong
            # het truong hop timeout ranh - ket qua la serial_monitor.py
            # bao "0 byte" mai mai du endpoint dang bi ket, khien nguoi
            # dung tuong nham la loi firmware/baud/mach reset trong khi
            # thuc chat chi can clear halt. Theo chuan USB, mot bulk
            # endpoint bi stall se tu dong tu choi MOI transfer tiep theo
            # cho toi khi host gui CLEAR_FEATURE(ENDPOINT_HALT) - do do o
            # day ta tu dong clearHalt() roi thu lai DUY NHAT MOT LAN. Neu
            # van fail, bao loi ro rang thay vi tiep tuc gia vo "im lang".
            try:
                self._handle.clearHalt(endpoint)
            except usb1.USBError as clear_exc:
                raise AndroidUsbError(
                    f"Endpoint 0x{endpoint:02x} bi STALL va khong clear duoc: {clear_exc}. "
                    "Hay rut cam lai day USB (STALL o muc phan cung/kernel usbfs "
                    "khong tu het duoc)."
                ) from clear_exc
            try:
                return self._handle.bulkRead(endpoint, length, timeout=timeout)
            except usb1.USBErrorTimeout as exc2:
                return bytes(getattr(exc2, "received", b"") or b"")
            except usb1.USBErrorPipe as exc2:
                raise AndroidUsbError(
                    f"Endpoint 0x{endpoint:02x} van bi STALL ngay sau khi clearHalt(): {exc2}. "
                    "Day thuong la do thiet bi/driver clone khong tuong thich hoan toan, "
                    "hoac phien USB dang bi giu boi tien trinh khac. Hay rut cam lai day USB."
                ) from exc2

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
