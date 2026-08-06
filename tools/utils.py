#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py
========
Các hàm tiện ích dùng chung: định dạng số liệu, retry decorator, kiểm
tra file, parse JSON an toàn. Không phụ thuộc PlatformIO, không dùng
serial.tools.list_ports, không enumerate tty. Thuần Python 3, tương
thích Termux (Android 10-16).
"""

from __future__ import annotations

import functools
import json
import os
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------
# Định dạng dữ liệu
# --------------------------------------------------------------------------


def format_size(num_bytes: float) -> str:
    """Định dạng số byte thành chuỗi dễ đọc (KB, MB, GB)."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024.0:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TB"


def format_speed(bytes_per_sec: float) -> str:
    return f"{format_size(bytes_per_sec)}/s"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_eta(bytes_done: int, bytes_total: int, elapsed: float) -> str:
    if bytes_done <= 0 or elapsed <= 0:
        return "--:--"
    speed = bytes_done / elapsed
    if speed <= 0:
        return "--:--"
    remaining = bytes_total - bytes_done
    return format_duration(remaining / speed)


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------


def retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator thử lại một hàm tối đa `max_attempts` lần nếu xảy ra lỗi."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(attempt, exc)
                        time.sleep(delay_seconds)
                    else:
                        raise
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# File / JSON
# --------------------------------------------------------------------------


def check_file_exists(path: str, min_size: int = 1) -> bool:
    """Kiểm tra file tồn tại và có kích thước tối thiểu."""
    return os.path.isfile(path) and os.path.getsize(path) >= min_size


def parse_json_safe(text: str) -> Optional[Any]:
    """Parse JSON an toàn, trả về None nếu lỗi thay vì raise exception."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def human_confirm(prompt: str, default_yes: bool = True) -> bool:
    """Hỏi xác nhận người dùng qua bàn phím (y/n)."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix}: ").strip().lower()
    except EOFError:
        return default_yes
    if not answer:
        return default_yes
    return answer in ("y", "yes", "co", "có", "c")


def hexdump(data: bytes, length: int = 16) -> str:
    """Trả về chuỗi hexdump đơn giản để debug dữ liệu nhị phân."""
    lines = []
    for i in range(0, len(data), length):
        chunk = data[i : i + length]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<{length * 3}}  {ascii_part}")
    return "\n".join(lines)
