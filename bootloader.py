#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Điều khiển BOOT/EN qua DTR/RTS CP210x theo trình tự Espressif."""

import time
from cp210x import CP210x

def enter_bootloader(uart: CP210x, manual=False):
    if manual:
        print("[THÔNG TIN] Giữ BOOT → nhấn EN/RESET → giữ 1–2 giây → thả BOOT.", flush=True)
        time.sleep(0.2)
        return
    # CP210x SET_MHS nhận trạng thái logic giống pySerial: True = asserted.
    # Mạch auto-reset của ESP32 là active-low ở phía chip. Trình tự chuẩn: 
    # DTR=0/RTS=1 (IO0 cao, EN thấp) → DTR=1/RTS=0 (IO0 thấp, EN cao)
    # → DTR=0/RTS=0 (IO0 cao, EN cao).
    uart.set_mhs(False, True)
    time.sleep(0.10)
    uart.set_mhs(True, False)
    time.sleep(0.05)
    uart.set_mhs(False, False)
    time.sleep(0.10)

def exit_bootloader(uart: CP210x):
    uart.set_mhs(False, True)
    time.sleep(0.10)
    uart.set_mhs(False, False)
