#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_detect.py
=============
Liệt kê thiết bị USB đang cắm và chọn thiết bị để thao tác.

THAY ĐỔI KIẾN TRÚC QUAN TRỌNG SO VỚI TOOLKIT CŨ (V1)
-----------------------------------------------------
Ở V1, luồng chọn thiết bị gọi `termux-usb -r -e` MỘT LẦN cho từng
thiết bị ứng viên chỉ để đọc VID/PID (dò tìm chip UART-USB đã biết),
sau đó lệnh thao tác thật sự (flash/monitor/...) lại gọi `termux-usb
-r -e` MỘT LẦN NỮA để thực thi. Hai vòng xin quyền tách biệt này là
nguồn gốc chính của lỗi "Permission denied" ngắt quãng: Android có
thể cấp quyền cho phiên dò tìm nhưng dialog bị đóng/timeout ở phiên
thao tác thật, hoặc người dùng chỉ bấm "Allow" một lần duy nhất theo
phản xạ rồi bỏ qua hộp thoại thứ hai.

Ở V2, việc CHỌN thiết bị chỉ dựa vào `termux-usb -l` (liệt kê đường
dẫn thô, KHÔNG cần cấp quyền, không mở fd). Việc đọc VID/PID, chọn
driver UART, và toàn bộ thao tác thật sự (flash/monitor/chip info/
erase/mac) đều diễn ra BÊN TRONG một phiên `termux-usb -r -e` DUY
NHẤT do esptool_android.py / serial_monitor.py tự quản lý. Nhờ vậy
toàn bộ vòng đời thiết bị chỉ xin quyền đúng một lần cho mỗi lần
chạy lệnh.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import os
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from utils import parse_json_safe  # noqa: E402


class UsbDetectError(RuntimeError):
    pass


def ensure_termux_api() -> None:
    if shutil.which("termux-usb") is None:
        raise UsbDetectError(
            "Khong tim thay lenh 'termux-usb'. Hay cai dat goi termux-api:\n"
            "  pkg install termux-api\n"
            "va cai ung dung 'Termux:API' tu F-Droid hoac Google Play."
        )


def list_usb_paths(timeout: float = 10.0) -> List[str]:
    """
    Liệt kê đường dẫn thiết bị USB đang cắm bằng `termux-usb -l`.
    KHÔNG yêu cầu cấp quyền, an toàn để gọi nhiều lần / trong doctor.sh.
    """
    ensure_termux_api()
    try:
        result = subprocess.run(
            ["termux-usb", "-l"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise UsbDetectError("termux-usb -l bi timeout. Kiem tra Termux:API da cai chua.") from exc

    if result.returncode != 0:
        raise UsbDetectError(f"termux-usb -l that bai: {result.stderr.strip()}")

    data = parse_json_safe(result.stdout)
    if data is None or not isinstance(data, list):
        raise UsbDetectError(f"Khong parse duoc ket qua termux-usb -l: {result.stdout!r}")
    return list(data)


def choose_device_path(paths: List[str]) -> str:
    """
    Chọn 1 đường dẫn thiết bị. Nếu chỉ có 1 thiết bị, tự động chọn.
    Nếu có nhiều, in danh sách và để người dùng chọn theo số thứ tự
    (chưa thể hiển thị tên chip vì chưa xin quyền / chưa đọc VID-PID).
    """
    if not paths:
        raise UsbDetectError(
            "Khong tim thay thiet bi USB nao. Kiem tra:\n"
            "  1. Cap OTG da cam dung chieu\n"
            "  2. Board ESP32 da cam vao cap OTG\n"
            "  3. Dien thoai ho tro USB Host (OTG)"
        )
    if len(paths) == 1:
        print(f"Da tim thay thiet bi USB tai: {paths[0]}", file=sys.stderr)
        return paths[0]

    print("\nTim thay nhieu thiet bi USB. Vui long chon:\n", file=sys.stderr)
    for idx, path in enumerate(paths, start=1):
        print(f"  {idx}. {path}", file=sys.stderr)
    print(
        "\n(Luu y: chua the hien thi ten chip vi VID/PID chi doc duoc "
        "sau khi Android cap quyen; neu khong chac, rut bot thiet bi USB "
        "khac va chi de lai ESP32.)\n",
        file=sys.stderr,
    )

    while True:
        try:
            choice = input(f"Nhap so thu tu [1-{len(paths)}]: ").strip()
            index = int(choice) - 1
            if 0 <= index < len(paths):
                return paths[index]
        except (ValueError, EOFError):
            pass
        print("Lua chon khong hop le, thu lai.", file=sys.stderr)


def find_device_path() -> str:
    """Điểm vào chính cho các script bash: liệt kê rồi chọn 1 đường dẫn."""
    paths = list_usb_paths()
    return choose_device_path(paths)


def main() -> int:
    try:
        print(find_device_path())
        return 0
    except UsbDetectError as exc:
        logger.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
