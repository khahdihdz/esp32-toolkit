#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
esp32_flash.py
==============
Luồng flash / readback / erase cho ESP32 classic ROM.

ESP32 USB Flasher v3
- Không dùng pyserial.
- Giao tiếp qua ESP32 ROM bootloader.
- Hỗ trợ Flash size được phát hiện từ JEDEC.
- Tự cấu hình SPI flash parameters trước FLASH_BEGIN.
- FLASH_BEGIN → FLASH_DATA → FLASH_END.
- FLASH_END không retry.
- Readback Flash để xác minh.
"""

from __future__ import annotations

import time
import hashlib

from esp32_rom import (
    ESP32ROM,
    FLASH_WRITE_SIZE,
    FLASH_SECTOR,
)

from verify import file_hashes


# ============================================================
# TIỆN ÍCH
# ============================================================

def pad4(data: bytes) -> bytes:
    """
    ESP32 ROM yêu cầu dữ liệu FLASH_DATA có kích thước phù hợp.

    Padding bằng 0xFF không làm thay đổi dữ liệu firmware thực.
    """
    padding = (-len(data)) % 4

    if padding:
        return data + (b"\xFF" * padding)

    return data


def validate_range(
    offset: int,
    size: int,
    flash_size: int | None,
) -> None:
    """
    Kiểm tra vùng firmware có nằm trong Flash hay không.
    """

    if offset < 0:
        raise ValueError("Offset không hợp lệ.")

    if size <= 0:
        raise ValueError("Kích thước firmware không hợp lệ.")

    if flash_size is not None:
        if offset + size > flash_size:
            raise ValueError(
                "Firmware vượt quá dung lượng Flash.\n"
                f"Offset: 0x{offset:X}\n"
                f"Firmware: {size:,} byte\n"
                f"Flash: {flash_size:,} byte"
            )


# ============================================================
# FLASH FIRMWARE
# ============================================================

def flash_file(
    rom: ESP32ROM,
    path: str,
    offset: int,
    flash_size: int | None = None,
):
    """
    Nạp một file BIN vào ESP32.

    Luồng:

        validate
            ↓
        hash firmware
            ↓
        pad 4 byte
            ↓
        SET_FLASH_PARAMS
            ↓
        FLASH_BEGIN
            ↓
        FLASH_DATA
            ↓
        FLASH_END
    """

    # --------------------------------------------------------
    # Đọc firmware
    # --------------------------------------------------------

    with open(path, "rb") as f:
        data = f.read()

    if not data:
        raise ValueError("Firmware rỗng.")

    validate_range(
        offset,
        len(data),
        flash_size,
    )

    # --------------------------------------------------------
    # Hash firmware gốc
    # --------------------------------------------------------

    md5, sha = file_hashes(path)

    print(
        f"Firmware: {path}",
        flush=True,
    )

    print(
        f"Dung lượng: {len(data):,} byte",
        flush=True,
    )

    print(
        f"MD5: {md5}",
        flush=True,
    )

    print(
        f"SHA-256: {sha}",
        flush=True,
    )

    # --------------------------------------------------------
    # Padding
    # --------------------------------------------------------

    image = pad4(data)

    print(
        f"[THÔNG TIN] Dữ liệu sau padding: "
        f"{len(image):,} byte",
        flush=True,
    )

    # --------------------------------------------------------
    # SET FLASH PARAMETERS
    #
    # Rất quan trọng:
    # Flash size được lấy từ JEDEC, không tự giả định 4 MB.
    # --------------------------------------------------------

    if flash_size is not None:

        print(
            f"[ĐANG LÀM] SET_FLASH_PARAMS "
            f"({flash_size:,} byte)",
            flush=True,
        )

        rom.set_flash_params(
            flash_size
        )

        print(
            "[THÀNH CÔNG] SET_FLASH_PARAMS",
            flush=True,
        )

    # --------------------------------------------------------
    # FLASH BEGIN
    # --------------------------------------------------------

    blocks = rom.flash_begin(
        len(image),
        offset,
    )

    print(
        f"[THÔNG TIN] FLASH_BEGIN: "
        f"{blocks} block × {FLASH_WRITE_SIZE} byte",
        flush=True,
    )

    # --------------------------------------------------------
    # FLASH DATA
    # --------------------------------------------------------

    start_time = time.monotonic()

    for seq in range(blocks):

        start = seq * FLASH_WRITE_SIZE
        end = start + FLASH_WRITE_SIZE

        block = image[start:end]

        # Block cuối cùng phải đủ FLASH_WRITE_SIZE.
        if len(block) < FLASH_WRITE_SIZE:
            block += b"\xFF" * (
                FLASH_WRITE_SIZE - len(block)
            )

        rom.flash_data(
            block,
            seq,
        )

        # Progress tính theo firmware thật,
        # không tính phần padding.
        done = min(
            len(data),
            (seq + 1) * FLASH_WRITE_SIZE,
        )

        pct = (
            done * 100.0 / len(data)
        )

        elapsed = max(
            0.001,
            time.monotonic() - start_time,
        )

        speed_kb = (
            done / elapsed / 1024
        )

        bar_len = 32
        filled = int(
            pct / 100.0 * bar_len
        )

        bar = (
            "█" * filled
            + " " * (bar_len - filled)
        )

        print(
            f"\rĐang ghi: "
            f"[{bar}] "
            f"{pct:6.2f}% | "
            f"{done:,}/{len(data):,} | "
            f"{speed_kb:,.1f} KB/s",
            end="",
            flush=True,
        )

    print(
        "",
        flush=True,
    )

    # --------------------------------------------------------
    # VERIFY MD5 TRÊN FLASH
    # --------------------------------------------------------
    #
    # SPI_FLASH_MD5 là cơ chế verify chính thức của ESP32.
    # Không gửi FLASH_END ở ROM-only mode. Lệnh này không bắt
    # buộc nếu host muốn giữ loader; sau khi MD5 khớp, worker
    # sẽ reset bằng DTR/RTS.
    #

    print(
        "[ĐANG LÀM] SPI_FLASH_MD5",
        flush=True,
    )

    flash_md5 = rom.flash_md5(
        offset,
        len(image),
    )

    expected_md5 = hashlib.md5(image).hexdigest()

    print(
        f"[THÔNG TIN] MD5 firmware (sau padding): {expected_md5}",
        flush=True,
    )

    print(
        f"[THÔNG TIN] MD5 Flash:                 {flash_md5}",
        flush=True,
    )

    if flash_md5.lower() != expected_md5.lower():
        raise RuntimeError(
            "MD5 FLASH KHÔNG KHỚP. Firmware chưa được xác minh an toàn."
        )

    print(
        "[THÀNH CÔNG] MD5 Flash khớp firmware.",
        flush=True,
    )

    print(
        "[THÔNG TIN] ROM-only: bỏ qua FLASH_END; "
        "sẽ reset ESP32 bằng DTR/RTS.",
        flush=True,
    )

    print(
        "[HOÀN TẤT] Ghi và xác minh firmware thành công.",
        flush=True,
    )

    return (
        len(data),
        md5,
        sha,
    )


# ============================================================
# READBACK
# ============================================================

def readback(
    rom: ESP32ROM,
    path: str,
    offset: int,
    length: int,
    flash_size: int | None = None,
):
    """
    Đọc dữ liệu từ Flash và lưu thành file.

    Có kiểm tra giới hạn theo Flash size.
    """

    validate_range(
        offset,
        length,
        flash_size,
    )

    print(
        f"[ĐANG LÀM] Đọc Flash "
        f"offset=0x{offset:X}, "
        f"size={length:,} byte",
        flush=True,
    )

    start_time = time.monotonic()

    def progress(done, total):

        pct = (
            done * 100.0 / total
            if total
            else 100.0
        )

        print(
            f"\rĐang đọc lại: "
            f"{pct:6.2f}% | "
            f"{done:,}/{total:,}",
            end="",
            flush=True,
        )

    data = rom.read_flash_slow(
        offset,
        length,
        progress,
    )

    print(
        "",
        flush=True,
    )

    with open(
        path,
        "wb",
    ) as f:
        f.write(data)

    elapsed = time.monotonic() - start_time

    print(
        f"[THÀNH CÔNG] Readback: "
        f"{len(data):,} byte",
        flush=True,
    )

    print(
        f"[THÔNG TIN] Thời gian đọc: "
        f"{elapsed:.2f}s",
        flush=True,
    )

    return (
        data,
        elapsed,
    )


# ============================================================
# ERASE REGION
# ============================================================

def erase_region(
    rom: ESP32ROM,
    offset: int,
    size: int,
):
    """
    Xóa một vùng Flash.

    offset và size phải căn theo sector 4096 byte.
    """

    if offset % FLASH_SECTOR != 0:
        raise ValueError(
            "Offset xóa phải căn theo sector "
            f"{FLASH_SECTOR} byte."
        )

    if size % FLASH_SECTOR != 0:
        raise ValueError(
            "Kích thước vùng xóa phải căn theo sector "
            f"{FLASH_SECTOR} byte."
        )

    if size <= 0:
        raise ValueError(
            "Kích thước vùng xóa không hợp lệ."
        )

    print(
        f"[ĐANG LÀM] Xóa Flash: "
        f"offset=0x{offset:X}, "
        f"size={size:,} byte",
        flush=True,
    )

    start_time = time.monotonic()

    def progress(done, total):

        pct = (
            done * 100.0 / total
            if total
            else 100.0
        )

        print(
            f"\rĐang xóa: "
            f"{pct:6.2f}% | "
            f"{done:,}/{total:,} byte",
            end="",
            flush=True,
        )

    rom.erase_by_flash_begin(
        offset,
        size,
        progress=progress,
    )

    print(
        "",
        flush=True,
    )

    elapsed = (
        time.monotonic()
        - start_time
    )

    print(
        "[THÀNH CÔNG] Xóa vùng Flash.",
        flush=True,
    )

    print(
        f"[THÔNG TIN] Thời gian: "
        f"{elapsed:.2f}s",
        flush=True,
    )

    return elapsed


# ============================================================
# ERASE TOÀN BỘ CHIP
# ============================================================

def erase_chip(
    rom: ESP32ROM,
):
    """
    Xóa toàn bộ Flash bằng ERASE_FLASH của ROM.

    Không cần biết dung lượng Flash trước.
    """

    print(
        "Đang xóa toàn bộ chip "
        "(có thể mất 30s–vài phút, vui lòng đợi)...",
        flush=True,
    )

    start_time = time.monotonic()

    rom.chip_erase()

    elapsed = (
        time.monotonic()
        - start_time
    )

    print(
        "[THÀNH CÔNG] Đã xóa toàn bộ Flash.",
        flush=True,
    )

    print(
        f"[THÔNG TIN] Thời gian xóa: "
        f"{elapsed:.2f}s",
        flush=True,
    )

    return elapsed