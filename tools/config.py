#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py
=========
Nạp cấu hình từ config/config.json và config/partition.json. Cho phép
người dùng tùy chỉnh baudrate, timeout, offset flash, danh sách chip
UART đã biết ... mà không cần sửa code Python.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
FIRMWARE_DIR = os.path.join(ROOT_DIR, "firmware")

_DEFAULT_CONFIG: Dict[str, Any] = {
    "reset_baud": 115200,
    "flash_baud": 460800,
    "monitor_baud": 115200,
    "supported_monitor_bauds": [115200, 230400, 460800, 921600],
    "usb_permission_timeout_sec": 60,
    "sync_max_retries": 5,
    "flash_max_retries": 3,
    "flash_write_size": 16384,
    "flash_retry_delay_sec": 2,
    "reconnect_initial_delay_sec": 1,
    "reconnect_max_delay_sec": 10,
    "known_uart_chips": {},
    "supported_chips": [],
}

_DEFAULT_PARTITION: Dict[str, Any] = {
    "offsets": {
        "bootloader": "0x1000",
        "partitions": "0x8000",
        "boot_app0": "0xe000",
        "firmware": "0x10000",
        "littlefs": "0x3D0000",
    },
    "files": {
        "bootloader": "firmware/bootloader.bin",
        "partitions": "firmware/partitions.bin",
        "boot_app0": "firmware/boot_app0.bin",
        "firmware": "firmware/firmware.bin",
        "littlefs": "firmware/littlefs.bin",
    },
    "required_files": ["bootloader", "partitions", "boot_app0", "firmware"],
    "optional_files": ["littlefs"],
}


def _load_json(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return dict(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(default)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(default)


def load_config() -> Dict[str, Any]:
    return _load_json(os.path.join(CONFIG_DIR, "config.json"), _DEFAULT_CONFIG)


def load_partition() -> Dict[str, Any]:
    return _load_json(os.path.join(CONFIG_DIR, "partition.json"), _DEFAULT_PARTITION)


def known_uart_chips() -> Dict[Tuple[int, int], str]:
    """Trả về map (vid, pid) -> tên chip, đọc từ config.json (khóa dạng 'VVVV:PPPP')."""
    cfg = load_config()
    raw: Dict[str, str] = cfg.get("known_uart_chips", {})
    result: Dict[Tuple[int, int], str] = {}
    for key, name in raw.items():
        try:
            vid_s, pid_s = key.split(":")
            result[(int(vid_s, 16), int(pid_s, 16))] = name
        except ValueError:
            continue
    return result


def partition_entries(include_optional: bool = True) -> List[Tuple[str, int, str]]:
    """
    Trả về danh sách (ten, offset, duong_dan_tuyet_doi) theo thứ tự ghi
    flash hợp lý, dựa trên partition.json. Chỉ bao gồm các mục có file
    tồn tại trên đĩa khi include_optional=True cho phần optional.
    """
    part = load_partition()
    offsets: Dict[str, str] = part.get("offsets", {})
    files: Dict[str, str] = part.get("files", {})
    required: List[str] = part.get("required_files", [])
    optional: List[str] = part.get("optional_files", [])

    order = required + (optional if include_optional else [])
    entries: List[Tuple[str, int, str]] = []
    for name in order:
        if name not in offsets or name not in files:
            continue
        offset = int(offsets[name], 0)
        rel_path = files[name]
        abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(ROOT_DIR, rel_path)
        entries.append((name, offset, abs_path))
    return entries
