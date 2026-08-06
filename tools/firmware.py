#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
firmware.py
===========
Thao tác cấp cao với firmware: ghi nhiều file vào flash theo offset
(có progress bar), xóa toàn chip, đọc flash ra file, xác minh MD5, và
đọc thông tin firmware image (.bin) mà không cần thiết bị.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import time
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
import config as toolkit_config  # noqa: E402
from esp_loader import EspRomLoader, EspLoaderError, FLASH_WRITE_SIZE  # noqa: E402
from progress import ProgressBar  # noqa: E402
from utils import format_size, check_file_exists  # noqa: E402


class FirmwareError(RuntimeError):
    pass


def write_one_file(loader: EspRomLoader, offset: int, path: str, write_size: int = FLASH_WRITE_SIZE) -> None:
    size = os.path.getsize(path)
    logger.info(f"Ghi {path} ({format_size(size)}) tai offset {offset:#x}")
    num_blocks = loader.flash_begin(size, offset, write_size=write_size)
    bar = ProgressBar(total=size, label="  ")
    with open(path, "rb") as f:
        for seq in range(num_blocks):
            chunk = f.read(write_size)
            if not chunk:
                break
            try:
                loader.flash_block(chunk, seq, write_size=write_size)
            except EspLoaderError:
                bar.note_retry()
                raise
            bar.add(len(chunk))
    bar.finish()


def write_flash_files(
    loader: EspRomLoader,
    entries: List[Tuple[int, str]],
    flash_baud: int = None,
    reset_baud: int = 115200,
) -> None:
    """
    entries: danh sách (offset, duong_dan_file). Tự động đổi baudrate
    trước khi ghi nếu flash_baud khác reset_baud, và reset chip sau
    khi ghi xong.
    """
    cfg = toolkit_config.load_config()
    if flash_baud is None:
        flash_baud = int(cfg.get("flash_baud", 460800))

    loader.spi_attach()
    if flash_baud and flash_baud != reset_baud:
        logger.info(f"Doi baudrate len {flash_baud} de tang toc do ghi...")
        loader.change_baudrate(flash_baud, reset_baud)

    total_size = sum(os.path.getsize(p) for _, p in entries)
    logger.info(f"Tong dung luong can ghi: {format_size(total_size)}")

    start_time = time.time()
    for offset, path in entries:
        write_one_file(loader, offset, path)

    loader.flash_finish(reboot=True)
    elapsed = time.time() - start_time
    loader.hard_reset()
    logger.ok(f"Flash hoan tat trong {elapsed:.1f} giay.")


def erase_flash(loader: EspRomLoader) -> None:
    logger.info("Dang xoa toan bo flash (co the mat 20-60 giay)...")
    print("Erasing...")
    loader.erase_flash()
    loader.hard_reset()
    print("Done")
    logger.ok("Da xoa flash thanh cong.")


def read_flash_to_file(loader: EspRomLoader, offset: int, size: int, output_path: str) -> None:
    bar = ProgressBar(total=size, label="  ")
    data = loader.read_flash(offset, size, progress_cb=bar.update)
    bar.finish()
    with open(output_path, "wb") as f:
        f.write(data)
    logger.ok(f"Da doc {format_size(len(data))} vao {output_path}")


def verify_flash(loader: EspRomLoader, offset: int, path: str) -> bool:
    if not check_file_exists(path):
        raise FirmwareError(f"Khong tim thay file: {path}")
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        local_md5 = hashlib.md5(f.read()).hexdigest()
    remote_md5 = loader.flash_md5(offset, size)
    if local_md5 == remote_md5:
        logger.ok(f"Xac minh THANH CONG. MD5: {local_md5}")
        return True
    logger.error(f"Xac minh THAT BAI. Local={local_md5} Remote={remote_md5}")
    return False


IMAGE_FLASH_MODES = {0: "QIO", 1: "QOUT", 2: "DIO", 3: "DOUT"}
IMAGE_FLASH_SIZES = {0: "1MB", 1: "2MB", 2: "4MB", 3: "8MB", 4: "16MB"}
IMAGE_FLASH_FREQS = {0: "40MHz", 1: "26MHz", 2: "20MHz", 15: "80MHz"}


def image_info(path: str) -> dict:
    if not check_file_exists(path):
        raise FirmwareError(f"Khong tim thay file: {path}")
    with open(path, "rb") as f:
        header = f.read(24)
    if len(header) < 8 or header[0] != 0xE9:
        raise FirmwareError("File khong phai firmware image hop le (thieu magic byte 0xE9).")
    magic, num_segments, flash_mode, flash_size_freq = struct.unpack("<BBBB", header[:4])
    entry_point = struct.unpack("<I", header[4:8])[0]
    return {
        "magic": magic,
        "num_segments": num_segments,
        "flash_mode": IMAGE_FLASH_MODES.get(flash_mode, "Unknown"),
        "flash_size": IMAGE_FLASH_SIZES.get((flash_size_freq >> 4) & 0x0F, "Unknown"),
        "flash_speed": IMAGE_FLASH_FREQS.get(flash_size_freq & 0x0F, "Unknown"),
        "entry_point": entry_point,
        "file_size": os.path.getsize(path),
    }


def resolve_auto_entries(include_optional: bool = True) -> List[Tuple[int, str]]:
    """
    Lấy danh sách (offset, duong_dan) tự động theo config/partition.json,
    dùng cho `esptool_android.py flash_auto`. Bỏ qua littlefs nếu file
    không tồn tại (tùy chọn), báo lỗi nếu thiếu file bắt buộc.
    """
    entries: List[Tuple[int, str]] = []
    part = toolkit_config.load_partition()
    required = set(part.get("required_files", []))

    for name, offset, abs_path in toolkit_config.partition_entries(include_optional=include_optional):
        if not check_file_exists(abs_path):
            if name in required:
                raise FirmwareError(f"Thieu file firmware bat buoc: {abs_path}")
            logger.warning(f"Khong thay {abs_path} — bo qua (tuy chon).")
            continue
        entries.append((offset, abs_path))
    return entries
