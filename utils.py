#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiện ích chung cho ESP32 USB Flasher v3."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path


TERMUX_API = "/data/data/com.termux/files/usr/bin/termux-usb"
PYTHON = "/data/data/com.termux/files/usr/bin/python"

ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "usb_worker.py"
LOG_DIR = ROOT / "logs"

CALLBACK_DEFAULT = (
    Path(os.environ.get(
        "PREFIX",
        "/data/data/com.termux/files/usr"
    )) / "bin" / "espflash-usb-callback"
)

LIVE_LOG = Path.home() / "espflash-live.log"


# =========================================================
# THỜI GIAN / LOG
# =========================================================

def now_name() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S")


def log_path() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR / f"flash_{now_name()}.log"


# =========================================================
# HASH
# =========================================================

def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()

    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)

            if not data:
                break

            h.update(data)

    return h.hexdigest()


def md5_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()

    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)

            if not data:
                break

            h.update(data)

    return h.hexdigest()


# =========================================================
# PARSE
# =========================================================

def parse_int(value: str) -> int:
    return int(value, 0)


# =========================================================
# USB DEVICE
# =========================================================

def list_usb_devices() -> list[str]:

    if not os.path.exists(TERMUX_API):
        raise RuntimeError(
            "Không tìm thấy termux-usb.\n"
            "Hãy cài Termux:API và gói termux-api."
        )

    p = subprocess.run(
        [TERMUX_API, "-l"],
        text=True,
        capture_output=True,
    )

    if p.returncode != 0:
        raise RuntimeError(
            p.stderr.strip()
            or "termux-usb -l thất bại."
        )

    raw = p.stdout.strip()

    try:
        obj = json.loads(raw)

        if isinstance(obj, list):
            return [str(x) for x in obj]

    except json.JSONDecodeError:
        pass

    return re.findall(
        r"/dev/bus/usb/\d{3}/\d{3}",
        raw
    )


# =========================================================
# USB PERMISSION
# =========================================================

def ensure_usb_permission(device: str) -> None:

    print(
        f"[USB] Kiểm tra quyền truy cập: {device}",
        flush=True
    )

    if not os.path.exists(TERMUX_API):
        raise RuntimeError(
            "Không tìm thấy termux-usb."
        )

    try:

        p = subprocess.run(
            [
                TERMUX_API,
                "-r",
                device,
            ],
            text=True,
            capture_output=True,
            timeout=90,
        )

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            "Xin quyền USB quá lâu (>90s).\n"
            "Hãy kiểm tra hộp thoại quyền USB của Termux "
            "và bấm Allow/OK."
        )

    out = (
        (p.stdout or "")
        + (p.stderr or "")
    ).strip()

    print(
        f"[USB] termux-usb -r return={p.returncode}",
        flush=True
    )

    if out:
        print(
            f"[USB] termux-usb -r: {out}",
            flush=True
        )

    if p.returncode != 0:

        raise RuntimeError(
            "Android từ chối quyền truy cập USB.\n"
            f"Chi tiết: {out or 'không có phản hồi'}"
        )

    if "denied" in out.lower():

        raise RuntimeError(
            "Android từ chối quyền truy cập USB.\n"
            f"Chi tiết: {out}"
        )


# =========================================================
# ĐỌC LIVE LOG
# =========================================================

def read_live_log() -> str:

    try:

        if LIVE_LOG.exists():
            return LIVE_LOG.read_text(
                encoding="utf-8",
                errors="replace"
            )

    except Exception:
        pass

    return ""


def print_live_log_since(before: str = "") -> None:

    data = read_live_log()

    if not data:
        print(
            "[WORKER] Không có espflash-live.log.",
            flush=True
        )
        return

    if before and data.startswith(before):
        data = data[len(before):]

    if data:
        print(
            data,
            end="" if data.endswith("\n") else "\n",
            flush=True
        )


# =========================================================
# CHẠY USB WORKER
# =========================================================

def run_usb_worker(
    device: str,
    *args: str
) -> subprocess.CompletedProcess[str]:

    """
    Chạy usb_worker.py thông qua:

        termux-usb -e callback DEVICE

    Callback nhận USB FD ở argv cuối.

    Vì termux-usb -e không chuyển stdout của callback
    về shell hiện tại trên một số bản Termux/HONOR,
    worker ghi log vào ~/espflash-live.log.

    Hàm này sẽ đọc live log và đưa nó ra màn hình.
    """

    ensure_usb_permission(device)

    request_path = ROOT / ".worker_request.json"

    tmp_path = ROOT / (
        f".worker_request.{os.getpid()}.tmp"
    )

    payload = {
        "op": (
            args[1]
            if len(args) > 1
            and args[0] == "--op"
            else None
        ),
        "args": list(args),
    }

    print(
        f"[WORKER] Request: {request_path}",
        flush=True
    )

    print(
        "[WORKER] Payload:",
        json.dumps(
            payload,
            ensure_ascii=False
        ),
        flush=True
    )

    # -----------------------------------------------------
    # Ghi request atomically
    # -----------------------------------------------------

    tmp_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8",
    )

    tmp_path.replace(request_path)

    print(
        "[WORKER] Đã tạo .worker_request.json",
        flush=True
    )

    # -----------------------------------------------------
    # Callback
    # -----------------------------------------------------

    callback = os.environ.get(
        "ESPFLASH_USB_CALLBACK",
        str(CALLBACK_DEFAULT)
    )

    print(
        f"[WORKER] CALLBACK={callback}",
        flush=True
    )

    if not os.path.exists(callback):

        raise RuntimeError(
            "Không tìm thấy callback:\n"
            f"{callback}"
        )

    if not os.access(callback, os.X_OK):

        raise RuntimeError(
            "Callback không có quyền thực thi:\n"
            f"{callback}"
        )

    if not request_path.exists():

        raise RuntimeError(
            "Không tạo được request file:\n"
            f"{request_path}"
        )

    print(
        "[WORKER] Xác nhận request tồn tại.",
        flush=True
    )

    # -----------------------------------------------------
    # Lưu live log trước khi chạy
    # -----------------------------------------------------

    before_log = read_live_log()

    # -----------------------------------------------------
    # Gọi termux-usb
    # -----------------------------------------------------

    cmd = [
        TERMUX_API,
        "-e",
        callback,
        device,
    ]

    print(
        "[WORKER] Gọi:",
        " ".join(cmd),
        flush=True
    )

    try:

        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=300,
        )

    except subprocess.TimeoutExpired:

        print(
            "[LỖI] termux-usb -e timeout >300 giây.",
            flush=True
        )

        print(
            "[WORKER] Live log:",
            flush=True
        )

        print_live_log_since(before_log)

        return subprocess.CompletedProcess(
            cmd,
            124,
            "",
            "termux-usb callback timeout",
        )

    # -----------------------------------------------------
    # Kết quả termux-usb
    # -----------------------------------------------------

    print(
        f"[WORKER] termux-usb RETURN={proc.returncode}",
        flush=True
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if stdout.strip():

        print(
            "[WORKER] termux-usb STDOUT:",
            flush=True
        )

        print(
            stdout,
            end="" if stdout.endswith("\n") else "\n",
            flush=True
        )

    else:

        print(
            "[WORKER] termux-usb STDOUT:",
            flush=True
        )

    if stderr.strip():

        print(
            "[WORKER] termux-usb STDERR:",
            flush=True
        )

        print(
            stderr,
            end="" if stderr.endswith("\n") else "\n",
            flush=True
        )

    # -----------------------------------------------------
    # Đọc log callback
    # -----------------------------------------------------

    after_log = read_live_log()

    if after_log:

        print(
            "\n[WORKER] ===== LIVE LOG =====",
            flush=True
        )

        if before_log and after_log.startswith(before_log):
            new_log = after_log[len(before_log):]
        else:
            new_log = after_log

        if new_log.strip():

            print(
                new_log,
                end="" if new_log.endswith("\n") else "\n",
                flush=True
            )

        print(
            "[WORKER] ===== END LIVE LOG =====",
            flush=True
        )

    # -----------------------------------------------------
    # Xóa request nếu callback thành công
    # -----------------------------------------------------

    if proc.returncode == 0:

        try:

            request_path.unlink()

            print(
                "[WORKER] Đã xóa .worker_request.json",
                flush=True
            )

        except FileNotFoundError:
            pass

    else:

        print(
            "[WORKER] Giữ .worker_request.json "
            "để chẩn đoán lỗi.",
            flush=True
        )

    # -----------------------------------------------------
    # Dọn tmp
    # -----------------------------------------------------

    try:
        tmp_path.unlink()

    except FileNotFoundError:
        pass

    # -----------------------------------------------------
    # QUAN TRỌNG:
    # stdout trả về cho menu phải chứa live log.
    #
    # Nếu callback thành công nhưng termux-usb stdout
    # rỗng, menu vẫn phải nhận được kết quả.
    # -----------------------------------------------------

    # -----------------------------------------------------
    # Trả kết quả cho menu
    # -----------------------------------------------------
    # Live log đã được in ở phía trên.
    # Không đưa after_log vào stdout nữa để tránh
    # print_result() in lại toàn bộ callback log lần thứ hai.
    return subprocess.CompletedProcess(
        cmd,
        proc.returncode,
        stdout,
        stderr,
    )


# =========================================================
# FILE BIN
# =========================================================

def valid_bin(
    path: str | Path
) -> tuple[bool, str]:

    p = Path(path).expanduser()

    if not p.is_file():
        return False, "Không tìm thấy file."

    if p.stat().st_size <= 0:
        return False, "File rỗng."

    if p.suffix.lower() != ".bin":
        return False, "File phải có phần mở rộng .bin."

    return True, ""


# =========================================================
# NHẬN DIỆN FIRMWARE
# =========================================================

_MERGED_RULES: list[
    tuple[str, str, str]
] = [

    (
        r"merged.*\.bin$",
        "0x0",
        "Firmware gộp (merged)"
    ),

    (
        r".*\.factory\.bin$",
        "0x0",
        "Firmware gộp (factory image)"
    ),
]


_PART_RULES: list[
    tuple[str, str, str]
] = [

    (
        r"bootloader.*\.bin$",
        "0x1000",
        "Bootloader"
    ),

    (
        r"(partition[-_]table|partitions)([^/]*)\.bin$",
        "0x8000",
        "Bảng phân vùng"
    ),

    (
        r"boot_app0.*\.bin$",
        "0xE000",
        "boot_app0 / OTA data init"
    ),

    (
        r"ota_data_initial.*\.bin$",
        "0xE000",
        "OTA data init"
    ),

    (
        r"littlefs\.bin$",
        "0x290000",
        "LittleFS / Web Dashboard"
    ),
]


_APP_RULES: list[
    tuple[str, str, str]
] = [

    (
        r"firmware\.bin$",
        "0x10000",
        "Firmware (app)"
    ),

    (
        r"app\.bin$",
        "0x10000",
        "Firmware (app)"
    ),

    (
        r".*\.ino\.bin$",
        "0x10000",
        "Firmware (app, Arduino)"
    ),
]


def detect_firmware_files(
    directory: str | Path,
    max_depth: int = 3
) -> list[tuple[str, str, str]]:

    root = Path(directory).expanduser()

    if not root.is_dir():

        raise ValueError(
            f"Không phải thư mục hợp lệ: {root}"
        )

    files: list[Path] = []

    for depth_root, dirs, names in os.walk(root):

        rel_depth = len(
            Path(depth_root)
            .relative_to(root)
            .parts
        )

        if rel_depth >= max_depth:
            dirs[:] = []

        for name in names:

            if name.lower().endswith(".bin"):

                files.append(
                    Path(depth_root) / name
                )

    # Ưu tiên file gần thư mục gốc
    files.sort(
        key=lambda p: len(
            p.relative_to(root).parts
        )
    )

    def match(rules, path: Path):

        name = path.name.lower()

        for pattern, offset, label in rules:

            if re.match(pattern, name):

                return offset, label

        return None

    # -----------------------------------------------------
    # Firmware merged/factory
    # -----------------------------------------------------

    for f in files:

        m = match(
            _MERGED_RULES,
            f
        )

        if m:

            offset, label = m

            return [
                (
                    offset,
                    str(f),
                    label
                )
            ]

    # -----------------------------------------------------
    # Firmware nhiều file
    # -----------------------------------------------------

    found: dict[
        str,
        tuple[str, str]
    ] = {}

    dupes: list[str] = []

    for f in files:

        m = (
            match(_PART_RULES, f)
            or match(_APP_RULES, f)
        )

        if not m:
            continue

        offset, label = m

        if offset in found:

            dupes.append(
                f"{f} "
                f"(đã có {found[offset][0]} "
                f"ở cùng offset {offset})"
            )

            continue

        found[offset] = (
            str(f),
            label
        )

    if dupes:

        print(
            "[CẢNH BÁO] Bỏ qua file trùng offset:"
        )

        for item in dupes:
            print(
                "  -",
                item
            )

    result = [
        (
            off,
            path,
            label
        )
        for off, (path, label)
        in found.items()
    ]

    result.sort(
        key=lambda x: int(x[0], 0)
    )

    return result


# =========================================================
# FLASH SECTOR
# =========================================================

def round_up_sector(
    n: int,
    sector: int = 0x1000
) -> int:

    if n <= 0:
        return 0

    return (
        (n + sector - 1)
        // sector
    ) * sector


# =========================================================
# ERASE PRESETS
# =========================================================

ERASE_PRESETS: list[
    tuple[str, str, int, str]
] = [

    (
        "1",
        "0x1000",
        0x7000,
        "Bootloader"
    ),

    (
        "2",
        "0x8000",
        0x1000,
        "Partition table"
    ),

    (
        "3",
        "0xE000",
        0x1000,
        "boot_app0 / OTA data"
    ),

    (
        "4",
        "0x10000",
        0x100000,
        "Vùng ứng dụng"
    ),
]


# =========================================================
# HIỂN THỊ RESULT
# =========================================================

def print_result(
    cp: subprocess.CompletedProcess[str]
) -> None:

    if cp.stdout:

        print(
            cp.stdout,
            end=(
                ""
                if cp.stdout.endswith("\n")
                else "\n"
            )
        )

    if cp.stderr:

        print(
            cp.stderr,
            end=(
                ""
                if cp.stderr.endswith("\n")
                else "\n"
            )
        )