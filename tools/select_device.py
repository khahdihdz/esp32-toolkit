#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select_device.py
==================
Dò tìm thiết bị USB, lọc ra ESP32/ESP8266 (theo VID/PID chip UART-USB
đã biết), cho người dùng chọn nếu có nhiều thiết bị, rồi in ĐÚNG MỘT
DÒNG là đường dẫn thiết bị ra stdout để các script bash (common.sh)
capture bằng `$(...)`.

Mọi thông báo log khác được ghi ra stderr để không lẫn vào stdout.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from usb_helper import find_esp32_candidates, choose_device, UsbHelperError  # noqa: E402


def main() -> int:
    try:
        candidates = find_esp32_candidates()
        device = choose_device(candidates)
        print(device.path)
        return 0
    except UsbHelperError as exc:
        logger.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
