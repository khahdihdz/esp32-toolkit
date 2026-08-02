#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py
========
Các hàm tiện ích dùng chung cho toàn bộ bộ công cụ ESP32-on-Android/Termux.

Không phụ thuộc PlatformIO, không dùng serial.tools.list_ports, không
enumerate tty. Toàn bộ hàm ở đây hoạt động thuần Python 3, tương thích
Termux (Android 10-15) và Python 3.14.
"""

from __future__ import annotations

import functools
import json
import os
import sys
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
    """Định dạng tốc độ truyền dữ liệu (byte/giây)."""
    return f"{format_size(bytes_per_sec)}/s"


def format_duration(seconds: float) -> str:
    """Định dạng thời gian thành chuỗi mm:ss hoặc hh:mm:ss."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_eta(bytes_done: int, bytes_total: int, elapsed: float) -> str:
    """Ước lượng thời gian còn lại (ETA) dựa trên tốc độ hiện tại."""
    if bytes_done <= 0 or elapsed <= 0:
        return "--:--"
    speed = bytes_done / elapsed
    if speed <= 0:
        return "--:--"
    remaining = bytes_total - bytes_done
    return format_duration(remaining / speed)


# --------------------------------------------------------------------------
# Progress bar / Spinner (ANSI)
# --------------------------------------------------------------------------

_FULL_BLOCK = "█"
_EMPTY_BLOCK = "░"


class ProgressBar:
    """
    Thanh tiến trình dạng ANSI hiển thị %, tốc độ, thời gian và ETA.

    Ví dụ hiển thị:
        [██████████░░░░░░░░░░]  50.0%  120.5 KB/s  ETA 00:12
    """

    def __init__(self, total: int, width: int = 30, label: str = "") -> None:
        self.total = max(total, 1)
        self.width = width
        self.label = label
        self.start_time = time.time()
        self.done = 0
        self._last_render_len = 0

    def update(self, done: int) -> None:
        self.done = min(done, self.total)
        self._render()

    def add(self, delta: int) -> None:
        self.update(self.done + delta)

    def _render(self) -> None:
        elapsed = time.time() - self.start_time
        ratio = self.done / self.total
        filled = int(self.width * ratio)
        bar = _FULL_BLOCK * filled + _EMPTY_BLOCK * (self.width - filled)
        speed = self.done / elapsed if elapsed > 0 else 0
        eta = format_eta(self.done, self.total, elapsed)
        line = (
            f"\r{self.label}[{bar}] {ratio * 100:5.1f}%  "
            f"{format_size(self.done)}/{format_size(self.total)}  "
            f"{format_speed(speed)}  ETA {eta}  "
            f"{format_duration(elapsed)}"
        )
        pad = max(0, self._last_render_len - len(line))
        sys.stdout.write(line + (" " * pad))
        sys.stdout.flush()
        self._last_render_len = len(line)

    def finish(self) -> None:
        self.update(self.total)
        sys.stdout.write("\n")
        sys.stdout.flush()


class Spinner:
    """Spinner ANSI đơn giản dùng cho các tác vụ không xác định tiến độ."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "") -> None:
        self.message = message
        self._idx = 0
        self._start = time.time()

    def spin(self) -> None:
        frame = self.FRAMES[self._idx % len(self.FRAMES)]
        elapsed = format_duration(time.time() - self._start)
        sys.stdout.write(f"\r{frame} {self.message} ({elapsed})")
        sys.stdout.flush()
        self._idx += 1

    def stop(self, final_message: Optional[str] = None) -> None:
        sys.stdout.write("\r" + " " * (len(self.message) + 20) + "\r")
        if final_message:
            sys.stdout.write(final_message + "\n")
        sys.stdout.flush()


# --------------------------------------------------------------------------
# Retry / Timeout
# --------------------------------------------------------------------------


def retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator thử lại một hàm tối đa `max_attempts` lần nếu xảy ra lỗi.

    on_retry(lan_thu, loi) được gọi trước mỗi lần thử lại (nếu có).
    """

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


class TimeoutError_(Exception):
    """Lỗi hết thời gian chờ tùy chỉnh (tránh trùng builtin TimeoutError)."""


def run_with_timeout(func: Callable[..., T], timeout: float, *args: Any, **kwargs: Any) -> T:
    """
    Chạy hàm với giới hạn thời gian bằng cách polling thời gian thực thi.
    Lưu ý: hàm mục tiêu cần tự kiểm tra thời gian nếu là vòng lặp dài;
    hàm này chủ yếu dùng để bọc các lệnh I/O có timeout nội bộ riêng.
    """
    start = time.time()
    result = func(*args, **kwargs)
    if time.time() - start > timeout:
        raise TimeoutError_(f"Hết thời gian chờ sau {timeout}s")
    return result


# --------------------------------------------------------------------------
# Kiểm tra file / JSON / USB
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
    return answer in ("y", "yes", "có", "c")


def hexdump(data: bytes, length: int = 16) -> str:
    """Trả về chuỗi hexdump đơn giản để debug dữ liệu nhị phân."""
    lines = []
    for i in range(0, len(data), length):
        chunk = data[i : i + length]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<{length * 3}}  {ascii_part}")
    return "\n".join(lines)
