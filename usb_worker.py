#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_worker.py
=============
USB Worker cho ESP32 USB Flasher v3.

Luồng:
Termux menu
  -> termux-usb -e
  -> Python worker
  -> USB FD ở argv cuối (hoặc TERMUX_USB_FD nếu có)
  -> usbdevfs.py
  -> CP210x
  -> ESP32 ROM

Mục tiêu:
- Không dùng pyserial / pyusb / libusb.
- Dùng trực tiếp file descriptor do termux-usb truyền qua TERMUX_USB_FD.
- Cấu hình CP210x.
- SYNC ESP32 ROM.
- READ_REG / kiểm tra chip.
- SPI_ATTACH.
- Tự đọc JEDEC ID và dung lượng Flash bằng esp32_rom.py.
- Không tự giả định Flash 4 MB.
"""

from __future__ import annotations

import os
import sys
import traceback
import base64
import json
from pathlib import Path

from esp32_flash import flash_file
from bootloader import enter_bootloader, exit_bootloader

from cp210x import CP210x
from esp32_rom import ESP32ROM, ROMError
from usbdevfs import USBError


def log(msg: str) -> None:
    print(msg, flush=True)


def get_usb_fd() -> int:
    """Lấy USB FD từ TERMUX_USB_FD hoặc argument cuối của callback."""
    env_fd = os.environ.get("TERMUX_USB_FD")
    if env_fd:
        try:
            return int(env_fd)
        except ValueError:
            pass

    # termux-usb -e truyền FD ở argument cuối.
    if len(sys.argv) >= 2:
        try:
            return int(sys.argv[-1])
        except ValueError:
            pass

    raise RuntimeError(
        "Không tìm thấy USB FD. Hãy chạy worker qua termux-usb -e "
        "(FD nằm ở argument cuối) hoặc -E (TERMUX_USB_FD)."
    )


def get_worker_args() -> list[str]:
    """Lấy tham số nghiệp vụ từ request file hoặc argv.

    USB FD là số nguyên cuối argv và được giữ lại cho get_usb_fd().
    Request file được dùng vì environment của callback không được bảo đảm
    truyền nguyên vẹn qua termux-usb.
    """
    request_file = None
    argv_args = []
    i = 1
    while i < len(sys.argv):
        a = str(sys.argv[i])
        if a == "--request-file" and i + 1 < len(sys.argv):
            request_file = sys.argv[i + 1]
            i += 2
            continue
        argv_args.append(a)
        i += 1

    if request_file:
        p = Path(request_file).expanduser()
        if not p.is_file():
            raise RuntimeError(f"Không tìm thấy worker request: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw = raw.get("args")
            if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
                raise ValueError("request không phải danh sách chuỗi hoặc object có trường args")
            return raw
        except Exception as e:
            raise RuntimeError(f"Worker request không hợp lệ: {e}") from e

    encoded = os.environ.get("ESPFLASH_WORKER_ARGS_B64", "")
    if encoded:
        try:
            raw = base64.b64decode(encoded).decode("utf-8")
            args = json.loads(raw)
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("request không phải danh sách chuỗi")
            return args
        except Exception as e:
            raise RuntimeError(f"ESPFLASH_WORKER_ARGS_B64 không hợp lệ: {e}") from e

    return [a for a in argv_args if not str(a).isdigit()]

def parse_operation(args: list[str]) -> tuple[str, str | None, int | None]:
    op = "detect"
    path = None
    offset = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--op" and i + 1 < len(args):
            op = args[i + 1]; i += 2; continue
        if a == "--file" and i + 1 < len(args):
            path = str(Path(args[i + 1]).expanduser()); i += 2; continue
        if a == "--offset" and i + 1 < len(args):
            offset = int(args[i + 1], 0); i += 2; continue
        i += 1
    return op, path, offset

def configure_cp210x(fd: int, debug: bool = False) -> CP210x:
    uart = CP210x(fd, debug=debug)

    log("[THÔNG TIN] CP2102 VID=10C4 PID=EA60")

    uart.configure(115200)

    log("[THÀNH CÔNG] IFC_ENABLE")
    log("[THÀNH CÔNG] SET_BAUDRATE")
    log("[THÀNH CÔNG] SET_LINE_CTL 8N1")
    log("[THÀNH CÔNG] SET_MHS")

    return uart


def detect_flash(rom: ESP32ROM) -> dict:
    """
    Đọc JEDEC ID sau SPI_ATTACH.

    Không được coi lỗi JEDEC là lỗi SYNC/USB.
    SPI_ATTACH đã thành công thì báo riêng lỗi Flash detection.
    """
    try:
        flash = rom.detect_flash_size()

        log(
            f"[THÀNH CÔNG] JEDEC ID: "
            f"{flash['jedec_id']}"
        )

        log(
            f"[THÔNG TIN] Flash: "
            f"{flash['size_mb']:.0f} MB "
            f"({flash['size_bytes']} bytes)"
        )

        log(
            f"[THÔNG TIN] Manufacturer: "
            f"0x{flash['manufacturer']:02X}"
        )

        log(
            f"[THÔNG TIN] Memory type: "
            f"0x{flash['memory_type']:02X}"
        )

        log(
            f"[THÔNG TIN] Capacity code: "
            f"0x{flash['capacity']:02X}"
        )
        return flash

    except Exception as e:
        log(
            f"[CẢNH BÁO] Không đọc được JEDEC/Flash size: "
            f"{type(e).__name__}: {e}"
        )
        return {}


def run(debug: bool = False) -> int:
    fd = get_usb_fd()
    args = get_worker_args()

    # --debug được truyền trực tiếp trong worker request.
    # Không phụ thuộc riêng vào biến môi trường ESP32_DEBUG.
    if "--debug" in args:
        debug = True

    op, firmware_path, offset = parse_operation(args)

    log("[ĐANG LÀM] termux-usb → Python USB Worker")
    log(f"[THÔNG TIN] USB_FD={fd}")
    log(f"[THÔNG TIN] OP={op}")

    uart = None

    try:
        uart = configure_cp210x(fd, debug=debug)

        # Đưa ESP32 vào ROM Download Mode trước khi gửi SYNC.
        log("[ĐANG LÀM] Đưa ESP32 vào Download Mode")
        enter_bootloader(uart)
        log("[THÀNH CÔNG] Đã chuyển sang Download Mode")


        rom = ESP32ROM(
            uart,
            baud=115200,
            debug=debug,
        )

        # ---------------------------------------------------------
        # 1. SYNC
        # ---------------------------------------------------------
        rom.sync(retries=5)
        log("[THÀNH CÔNG] ESP32 SYNC")

        # ---------------------------------------------------------
        # 2. DETECT CHIP / READ_REG
        # ---------------------------------------------------------
        chip = rom.detect_chip()
        log(f"[THÀNH CÔNG] Chip: {chip}")
        log(f"[THÔNG TIN] Magic: 0x{rom.magic:08X}")
        log("[THÀNH CÔNG] READ_REG")

        # ---------------------------------------------------------
        # 3. SPI ATTACH
        # ---------------------------------------------------------
        rom.spi_attach()
        log("[THÀNH CÔNG] SPI_ATTACH")

        # ---------------------------------------------------------
        # 4. JEDEC / FLASH SIZE
        # ---------------------------------------------------------
        flash_info = detect_flash(rom)

        flash_size = flash_info.get("size_bytes")

        if not flash_size:
            raise RuntimeError(
                "Không xác định được dung lượng Flash."
            )

        log(
            "[ĐANG LÀM] Cấu hình SPI Flash: "
            f"{flash_size} bytes"
        )

        rom.set_flash_params(flash_size)

        log("[THÀNH CÔNG] SPI_SET_PARAMS")

        if op == "flash":
            if not firmware_path:
                raise ValueError("Thiếu --file cho thao tác flash.")
            if offset is None:
                raise ValueError("Thiếu --offset cho thao tác flash.")
            flash_size = flash_info.get("size_bytes")
            log(
                f"[ĐANG LÀM] Flash firmware @ 0x{offset:X}: "
                f"{firmware_path}"
            )
            flash_file(
                rom,
                firmware_path,
                offset,
                flash_size=flash_size,
            )

            log("[ĐANG LÀM] Thoát Download Mode / reset ESP32")
            exit_bootloader(uart)
            log("[THÀNH CÔNG] ESP32 đã được reset")
        elif op in {"detect", "info"}:
            pass
        elif op == "erase-chip":
            flash_size = flash_info.get("size_bytes")

            if not flash_size:
                raise RuntimeError(
                    "Không xác định được dung lượng Flash."
                )

            log(
                "[ĐANG LÀM] Xóa toàn bộ Flash bằng "
                f"FLASH_BEGIN (0x02), "
                f"{flash_size} bytes"
            )

            rom.chip_erase(
                flash_size,
                offset=0,
            )

            log(
                "[THÀNH CÔNG] Đã xóa toàn bộ Flash"
            )
        else:
            raise ValueError(f"Thao tác không hỗ trợ: {op}")

        log("[HOÀN TẤT] USB Worker ESP32 v3")

        return 0

    except ROMError as e:
        log(f"[LỖI ROM] {e}")
        return 2

    except USBError as e:
        log(f"[LỖI USB] {e}")
        return 3

    except Exception as e:
        log(f"[LỖI] {type(e).__name__}: {e}")

        if debug:
            traceback.print_exc()

        return 1


def main() -> int:
    debug = (
        os.environ.get("ESP32_DEBUG", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )

    return run(debug=debug)


if __name__ == "__main__":
    sys.exit(main())
