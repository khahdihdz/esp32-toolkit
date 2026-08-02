#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mac.py
=======
Wrapper tối giản: chỉ in địa chỉ MAC của ESP32, gọi bởi mac.sh.

    python3 mac.py --device /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from android_esptool import open_loader, _read_mac  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="In địa chỉ MAC của ESP32")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        mac = _read_mac(loader)
        print("MAC:")
        print(mac)
        return 0
    finally:
        usb_dev.close()


if __name__ == "__main__":
    sys.exit(main())
