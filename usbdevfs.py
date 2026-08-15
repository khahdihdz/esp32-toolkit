#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USBDEVFS qua libc/ioctl; không dùng pyusb/libusb."""

from __future__ import annotations
import ctypes
import errno
import os
import time

libc = ctypes.CDLL(None, use_errno=True)

# Linux USBDEVFS ioctl numbers. ABI dùng chung trên Android/Linux cho arm64.
#
# SỬA LỖI QUAN TRỌNG: USBDEVFS_BULK trước đây là 0xC0105502 — con số này
# mã hoá kích thước struct usbdevfs_bulktransfer là 16 byte, tức tính theo
# ABI 32-bit (con trỏ `data` 4 byte: ep(4)+len(4)+timeout(4)+data(4)=16).
# Nhưng Termux chạy tiến trình arm64 gọi thẳng kernel arm64 (không qua
# compat layer), nên con trỏ `data` thực tế là 8 byte và struct có padding
# 4 byte trước con trỏ để căn chỉnh 8-byte, làm kích thước thật là 24 byte
# (ep(4)+len(4)+timeout(4)+pad(4)+data(8)=24). Vì số ioctl cũ không khớp
# với case USBDEVFS_BULK mà driver usbfs của kernel 64-bit dùng, MỌI lệnh
# Bulk OUT/IN đều bị kernel từ chối ngay từ ioctl() — không liên quan gì
# tới phần cứng CP2102 hay ESP32. Đây chính là nguyên nhân "SYNC thất bại
# sau 5 lần thử": gói SYNC cần gửi qua Bulk OUT nhưng chưa từng gửi được.
# USBDEVFS_CONTROL tính đúng từ trước (size=24, con trỏ 8 byte) nên các
# bước control transfer (IFC_ENABLE, SET_BAUDRATE, SET_MHS...) không lỗi.
USBDEVFS_CONTROL = 0xC0185500
USBDEVFS_BULK = 0xC0185502
# USBDEVFS_CLAIMINTERFACE: termux-usb chỉ mở fd cho tiến trình, KHÔNG tự
# claim interface. Một số kernel Android tự "auto-claim" khi thấy control/
# bulk transfer đầu tiên (kèm cảnh báo trong dmesg), nhưng không phải máy
# nào cũng vậy — thiếu bước claim rõ ràng có thể gây lỗi ngắt quãng
# (EBUSY/EACCES) tuỳ kernel. _IOR('U', 15, unsigned int).
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x80045510

class CtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_ubyte),
        ("bRequest", ctypes.c_ubyte),
        ("wValue", ctypes.c_ushort),
        ("wIndex", ctypes.c_ushort),
        ("wLength", ctypes.c_ushort),
        ("timeout", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]

class BulkTransfer(ctypes.Structure):
    _fields_ = [
        ("ep", ctypes.c_uint),
        ("len", ctypes.c_uint),
        ("timeout", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]

class USBError(RuntimeError):
    pass

class USBTimeoutError(USBError):
    """Hết thời gian chờ dữ liệu ở MỘT lần poll (ETIMEDOUT/EAGAIN).

    Đây KHÔNG phải lỗi phần cứng thật — nó là kết quả bình thường khi
    thiết bị chưa kịp trả lời trong khoảng timeout ngắn của một lần
    ioctl() bulk transfer. Lớp gọi (vòng lặp poll ở esp32_rom._read_frame)
    cần bắt riêng loại lỗi này để tiếp tục poll cho tới hết deadline tổng,
    thay vì để nó thoát ra như một lỗi USB thật (EPIPE/ENODEV/EIO...).
    """
    pass

def _err(prefix: str) -> USBError:
    e = ctypes.get_errno()
    names = {
        errno.EPIPE: "EPIPE: endpoint STALL",
        errno.ENODEV: "ENODEV: thiết bị đã ngắt kết nối",
        errno.ETIMEDOUT: "ETIMEDOUT: quá thời gian",
        errno.EINTR: "EINTR: syscall bị gián đoạn",
        errno.EAGAIN: "EAGAIN: tạm thời chưa có dữ liệu",
        errno.EIO: "EIO: lỗi I/O USB",
    }
    msg = f"{prefix}: {names.get(e, os.strerror(e))} (errno={e})"
    # ETIMEDOUT/EAGAIN trên một lần bulk transfer đơn lẻ chỉ có nghĩa
    # "chưa có dữ liệu trong khoảng timeout_ms này" — bình thường khi
    # đang poll phản hồi. Không coi là lỗi USB thật.
    if e in (errno.ETIMEDOUT, errno.EAGAIN):
        return USBTimeoutError(msg)
    return USBError(msg)

def ioctl_control(fd: int, request_type: int, request: int, value: int, index: int,
                  data: bytes = b"", timeout_ms: int = 1000) -> bytes:
    buf = ctypes.create_string_buffer(data, max(1, len(data)))
    tr = CtrlTransfer(request_type, request, value, index, len(data), timeout_ms,
                      ctypes.cast(buf, ctypes.c_void_p))
    ret = libc.ioctl(fd, USBDEVFS_CONTROL, ctypes.byref(tr))
    if ret < 0:
        raise _err("USB control transfer lỗi")
    return bytes(buf.raw[:max(0, ret)])

def bulk_write(fd: int, ep: int, data: bytes, timeout_ms: int = 3000) -> int:
    buf = ctypes.create_string_buffer(data, max(1, len(data)))
    tr = BulkTransfer(ep, len(data), timeout_ms, ctypes.cast(buf, ctypes.c_void_p))
    ret = libc.ioctl(fd, USBDEVFS_BULK, ctypes.byref(tr))
    if ret < 0:
        raise _err("USB Bulk OUT lỗi")
    return ret

def bulk_read(fd: int, ep: int, size: int = 4096, timeout_ms: int = 1000) -> bytes:
    buf = ctypes.create_string_buffer(size)
    tr = BulkTransfer(ep, size, timeout_ms, ctypes.cast(buf, ctypes.c_void_p))
    ret = libc.ioctl(fd, USBDEVFS_BULK, ctypes.byref(tr))
    if ret < 0:
        raise _err("USB Bulk IN lỗi")
    return bytes(buf.raw[:ret])

def claim_interface(fd: int, interface: int = 0) -> None:
    # Claim interface trước khi dùng control (recipient=interface) hoặc
    # bulk transfer. Bỏ qua lỗi "đã claim rồi" (EBUSY do gọi lại) một cách
    # an toàn ở lớp gọi, hàm này chỉ báo lỗi thật.
    val = ctypes.c_uint(interface)
    ret = libc.ioctl(fd, USBDEVFS_CLAIMINTERFACE, ctypes.byref(val))
    if ret < 0:
        raise _err("USB Claim interface lỗi")

def release_interface(fd: int, interface: int = 0) -> None:
    val = ctypes.c_uint(interface)
    ret = libc.ioctl(fd, USBDEVFS_RELEASEINTERFACE, ctypes.byref(val))
    if ret < 0:
        raise _err("USB Release interface lỗi")
