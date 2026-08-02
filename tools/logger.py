#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logger.py
=========
Logging có màu ANSI cho toàn bộ bộ công cụ. Không dùng module `logging`
chuẩn để giữ output đơn giản, đẹp mắt và dễ đọc trên terminal Termux
(kể cả các terminal Android không hỗ trợ đầy đủ mã màu 256).
"""

from __future__ import annotations

import sys
import time


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_CYAN = "\033[96m"


def _supports_color() -> bool:
    """Kiểm tra terminal hiện tại có hỗ trợ màu ANSI hay không."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


_COLOR_ENABLED = _supports_color()


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _write(tag: str, color: str, message: str, stream=sys.stderr) -> None:
    ts = _timestamp()
    if _COLOR_ENABLED:
        line = f"{Colors.DIM}[{ts}]{Colors.RESET} {color}{Colors.BOLD}[{tag}]{Colors.RESET} {message}"
    else:
        line = f"[{ts}] [{tag}] {message}"
    stream.write(line + "\n")
    stream.flush()


def info(message: str) -> None:
    _write("INFO", Colors.CYAN, message)


def ok(message: str) -> None:
    _write("OK", Colors.GREEN, message)


def warning(message: str) -> None:
    _write("WARNING", Colors.YELLOW, message)


def error(message: str) -> None:
    _write("ERROR", Colors.RED, message, stream=sys.stderr)


def debug(message: str) -> None:
    if "--debug" in sys.argv or "-v" in sys.argv:
        _write("DEBUG", Colors.MAGENTA, message)


def header(title: str) -> None:
    """In tiêu đề nổi bật, dùng để phân tách các bước lớn."""
    width = max(40, len(title) + 4)
    line = "═" * width
    if _COLOR_ENABLED:
        print(f"{Colors.BRIGHT_CYAN}{line}", file=sys.stderr)
        print(f"  {title}", file=sys.stderr)
        print(f"{line}{Colors.RESET}", file=sys.stderr)
    else:
        print(line, file=sys.stderr)
        print(f"  {title}", file=sys.stderr)
        print(line, file=sys.stderr)
