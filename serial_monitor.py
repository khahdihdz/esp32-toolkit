#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Serial Monitor ESP32 qua CP210x + termux-usb."""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

from cp210x import CP210x
from usbdevfs import USBError, USBTimeoutError


def get_fd() -> int:
    value = os.environ.get("TERMUX_USB_FD")

    if value:
        return int(value)

    raise RuntimeError(
        "Không tìm thấy TERMUX_USB_FD từ termux-usb."
    )


def reset_esp32(uart: CP210x):
    print("[RESET] Bắt đầu reset ESP32...", flush=True)

    # ESP32 DevKit + CP2102 auto-reset.
    #
    # DTR/RTS được điều khiển qua mạch auto-reset:
    #
    # RTS active -> giữ EN thấp
    # DTR active -> điều khiển IO0
    #
    # Chuỗi này tạo một xung reset rồi nhả ESP32.

    uart.set_mhs(False, True)
    print("[RESET] DTR=0 RTS=1", flush=True)
    time.sleep(0.10)

    uart.set_mhs(True, False)
    print("[RESET] DTR=1 RTS=0", flush=True)
    time.sleep(0.05)

    uart.set_mhs(False, False)
    print("[RESET] DTR=0 RTS=0", flush=True)

    # Cho ESP32 bắt đầu boot.
    time.sleep(0.02)

    print("[RESET] Hoàn tất.", flush=True)


def read_monitor(uart: CP210x, seconds: float):
    deadline = time.monotonic() + seconds

    print(
        f"[MONITOR] Đọc UART trong {seconds:.1f} giây...",
        flush=True,
    )

    while time.monotonic() < deadline:
        try:
            data = uart.bulk_read(
                4096,
                timeout_ms=100,
            )

            if not data:
                continue

            print(
                f"\n[RX] {len(data)} byte | "
                f"{data.hex(' ')}",
                flush=True,
            )

            text = data.decode(
                "utf-8",
                errors="replace",
            )

            print(
                "[TEXT] ",
                end="",
                flush=True,
            )

            print(
                text,
                end="",
                flush=True,
            )

        except USBTimeoutError:
            continue

        except USBError as e:
            print(
                f"\n[MONITOR] USB lỗi: {e}",
                flush=True,
            )
            raise


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
    )

    parser.add_argument(
        "--reset",
        action="store_true",
    )

    parser.add_argument(
        "--seconds",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--debug",
        action="store_true",
    )

    args = parser.parse_args()

    print(
        "================================",
        flush=True,
    )
    print(
        " ESP32 SERIAL MONITOR / CP210x",
        flush=True,
    )
    print(
        "================================",
        flush=True,
    )

    try:
        fd = get_fd()

        print(
            f"[USB] TERMUX_USB_FD={fd}",
            flush=True,
        )

        uart = CP210x(
            fd,
            debug=args.debug,
        )

        uart.configure(args.baud)

        print(
            f"[UART] CP2102 OK | "
            f"{args.baud} 8N1",
            flush=True,
        )

        if args.reset:
            reset_esp32(uart)

        # Đọc NGAY sau reset.
        read_monitor(
            uart,
            args.seconds,
        )

        print(
            "\n[MONITOR] Hoàn tất.",
            flush=True,
        )

        return 0

    except KeyboardInterrupt:
        print(
            "\n[MONITOR] Đã dừng.",
            flush=True,
        )
        return 0

    except Exception as e:
        print(
            f"\n[MONITOR] LỖI: "
            f"{type(e).__name__}: {e}",
            flush=True,
        )

        traceback.print_exc()

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
