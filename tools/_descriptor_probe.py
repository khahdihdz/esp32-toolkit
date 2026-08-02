#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_descriptor_probe.py
=====================
Script nội bộ, được `usb_helper.read_device_descriptor()` thực thi thông
qua `termux-usb -r -e`. Nhận đường dẫn thiết bị làm tham số cuối cùng
(do termux-usb tự thêm vào), mở thiết bị và in ra JSON gồm vendor_id /
product_id. KHÔNG gọi trực tiếp script này thủ công.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from android_usb_raw import AndroidUsbDevice, AndroidUsbError  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "thiếu đường dẫn thiết bị"}))
        return 1

    device_path = sys.argv[-1]
    try:
        with AndroidUsbDevice(device_path) as dev:
            vid, pid = dev.get_device_descriptor()
            print(json.dumps({"vendor_id": vid, "product_id": pid}))
            return 0
    except AndroidUsbError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
