#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
progress.py
===========
Hiển thị tiến trình dạng ANSI: % hoàn thành, tốc độ (KB/s), elapsed,
ETA, dùng cho flash/erase/read_flash. Cũng cung cấp Spinner cho các
thao tác không xác định trước tiến độ (vd: erase toàn chip).
"""

from __future__ import annotations

import sys
import time
from typing import Optional

from utils import format_duration, format_eta, format_size, format_speed

_FULL_BLOCK = "█"
_EMPTY_BLOCK = "░"


class ProgressBar:
    """
    Thanh tiến trình ANSI hiển thị %, tốc độ, elapsed và ETA.

    Ví dụ:
        [██████████░░░░░░░░░░]  50.0%  512.00 KB/1.00 MB  120.5 KB/s  ETA 00:12  00:04
    """

    def __init__(self, total: int, width: int = 30, label: str = "") -> None:
        self.total = max(total, 1)
        self.width = width
        self.label = label
        self.start_time = time.time()
        self.done = 0
        self.retry_count = 0
        self._last_render_len = 0

    def update(self, done: int) -> None:
        self.done = min(done, self.total)
        self._render()

    def add(self, delta: int) -> None:
        self.update(self.done + delta)

    def note_retry(self) -> None:
        self.retry_count += 1
        self._render()

    def _render(self) -> None:
        elapsed = time.time() - self.start_time
        ratio = self.done / self.total
        filled = int(self.width * ratio)
        bar = _FULL_BLOCK * filled + _EMPTY_BLOCK * (self.width - filled)
        speed = self.done / elapsed if elapsed > 0 else 0
        eta = format_eta(self.done, self.total, elapsed)
        retry_part = f"  retry={self.retry_count}" if self.retry_count else ""
        line = (
            f"\r{self.label}[{bar}] {ratio * 100:5.1f}%  "
            f"{format_size(self.done)}/{format_size(self.total)}  "
            f"{format_speed(speed)}  ETA {eta}  "
            f"{format_duration(elapsed)}{retry_part}"
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
