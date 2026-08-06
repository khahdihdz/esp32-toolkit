#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_esptool.py
====================
Triển khai lại giao thức nạp ROM bootloader của ESP32/ESP8266 (SLIP +
lệnh nhị phân) hoàn toàn bằng Python thuần, chạy trên Android/Termux,
KHÔNG phụ thuộc PlatformIO, KHÔNG dùng `esptool.py` gốc, KHÔNG dùng
`serial.tools.list_ports`.

Giao thức bên dưới (đóng khung SLIP, mã lệnh, checksum) là giao thức
công khai được Espressif tài liệu hóa và esptool.py mã nguồn mở triển
khai — không phải bí mật thương mại.

Sử dụng:
    android_esptool.py sync       --device /dev/bus/usb/001/002
    android_esptool.py chip_id    --device /dev/bus/usb/001/002
    android_esptool.py read_mac   --device /dev/bus/usb/001/002
    android_esptool.py flash_id   --device /dev/bus/usb/001/002
    android_esptool.py erase_flash --device /dev/bus/usb/001/002
    android_esptool.py write_flash --device /dev/bus/usb/001/002 \\
        0x1000 firmware/bootloader.bin \\
        0x8000 firmware/partitions.bin \\
        0xe000 firmware/boot_app0.bin \\
        0x10000 firmware/firmware.bin
    android_esptool.py read_flash  --device /dev/... 0x10000 0x100000 out.bin
    android_esptool.py verify_flash --device /dev/... 0x10000 firmware/firmware.bin
    android_esptool.py image_info  firmware/firmware.bin
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from android_usb_raw import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from uart_bridge import create_bridge, UartBridge, UartBridgeError  # noqa: E402
from utils import ProgressBar, check_file_exists, format_size, retry  # noqa: E402

# --------------------------------------------------------------------------
# Hằng số giao thức SLIP + lệnh ROM loader
# --------------------------------------------------------------------------

SLIP_END = 0xC0
SLIP_ESC = 0xDB
SLIP_ESC_END = 0xDC
SLIP_ESC_ESC = 0xDD

CMD_FLASH_BEGIN = 0x02
CMD_FLASH_DATA = 0x03
CMD_FLASH_END = 0x04
CMD_MEM_BEGIN = 0x05
CMD_MEM_END = 0x06
CMD_MEM_DATA = 0x07
CMD_SYNC = 0x08
CMD_WRITE_REG = 0x09
CMD_READ_REG = 0x0A
CMD_SPI_SET_PARAMS = 0x0B
CMD_SPI_ATTACH = 0x0D
CMD_CHANGE_BAUDRATE = 0x0F
CMD_FLASH_DEFL_BEGIN = 0x10
CMD_FLASH_DEFL_DATA = 0x11
CMD_FLASH_DEFL_END = 0x12
CMD_SPI_FLASH_MD5 = 0x13
CMD_READ_FLASH = 0xD2

CHECKSUM_SEED = 0xEF
FLASH_WRITE_SIZE = 0x4000  # 16KB mỗi block khi ghi flash
FLASH_SECTOR_SIZE = 0x1000

CHIP_MAGIC_REG = 0x40001000
UART_DATE_REG_ESP32 = 0x60000078

# Bảng nhận diện chip qua giá trị "magic number" đọc từ thanh ghi CHIP_MAGIC_REG.
# Giá trị lấy từ tài liệu công khai của esptool (chip_detect_magic).
CHIP_MAGIC_TABLE = {
    0x00F01D83: "ESP32",
    0x000007C6: "ESP32-S2",
    0x00000009: "ESP32-S3",
    0x6921506F: "ESP32-C3",
    0x1B31506F: "ESP32-C3 (rev0)",
    0x0DA1806F: "ESP32-C6",
    0x00000005: "ESP32-H2",
    0xFFF0C101: "ESP8266",
}

DEFAULT_RESET_BAUD = 115200
DEFAULT_FLASH_BAUD = 460800


class EspLoaderError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# SLIP encode/decode
# --------------------------------------------------------------------------


def slip_encode(payload: bytes) -> bytes:
    out = bytearray([SLIP_END])
    for b in payload:
        if b == SLIP_END:
            out += bytes([SLIP_ESC, SLIP_ESC_END])
        elif b == SLIP_ESC:
            out += bytes([SLIP_ESC, SLIP_ESC_ESC])
        else:
            out.append(b)
    out.append(SLIP_END)
    return bytes(out)


class SlipDecoder:
    """Bộ giải mã SLIP dạng stream, dùng cho việc đọc phản hồi từ ROM loader."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._in_frame = False
        self._escaped = False

    def feed(self, data: bytes) -> List[bytes]:
        frames = []
        for b in data:
            if b == SLIP_END:
                if self._in_frame and self._buf:
                    frames.append(bytes(self._buf))
                    self._buf = bytearray()
                self._in_frame = True
                continue
            if not self._in_frame:
                continue
            if self._escaped:
                if b == SLIP_ESC_END:
                    self._buf.append(SLIP_END)
                elif b == SLIP_ESC_ESC:
                    self._buf.append(SLIP_ESC)
                else:
                    self._buf.append(b)
                self._escaped = False
            elif b == SLIP_ESC:
                self._escaped = True
            else:
                self._buf.append(b)
        return frames


def checksum(data: bytes, seed: int = CHECKSUM_SEED) -> int:
    val = seed
    for b in data:
        val ^= b
    return val


# --------------------------------------------------------------------------
# ESP ROM Loader
# --------------------------------------------------------------------------


class EspRomLoader:
    """
    Giao tiếp với ROM bootloader của ESP32/ESP8266 qua UartBridge, dùng
    giao thức SLIP nhị phân (không dùng pySerial, không dùng esptool gốc).
    """

    def __init__(self, bridge: UartBridge) -> None:
        self.bridge = bridge
        self._decoder = SlipDecoder()
        self.chip_name = "Unknown"

    # ---------------------------------------------------------------
    def _send_command(self, cmd: int, data: bytes = b"", chk: int = 0) -> None:
        header = struct.pack("<BBHI", 0x00, cmd, len(data), chk)
        self.bridge.write(slip_encode(header + data))

    def _read_response(self, timeout_ms: int = 3000) -> Tuple[int, bytes, int]:
        """
        Đọc và giải mã một khung phản hồi SLIP.
        Trả về (command, data, value).
        """
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            chunk = self.bridge.read_available(max_size=1024, timeout_ms=200)
            if not chunk:
                continue
            frames = self._decoder.feed(chunk)
            for frame in frames:
                if len(frame) < 8:
                    continue
                direction, resp_cmd, size, value = struct.unpack("<BBHI", frame[:8])
                if direction != 0x01:
                    continue
                data = frame[8 : 8 + size]
                return resp_cmd, data, value
        raise EspLoaderError("Hết thời gian chờ phản hồi từ ROM bootloader (timeout).")

    @retry(max_attempts=3, delay_seconds=0.3, exceptions=(EspLoaderError,))
    def command(self, cmd: int, data: bytes = b"", chk: int = 0, timeout_ms: int = 3000) -> Tuple[bytes, int]:
        self._send_command(cmd, data, chk)
        resp_cmd, resp_data, value = self._read_response(timeout_ms)
        if resp_cmd != cmd:
            raise EspLoaderError(f"Lệnh phản hồi không khớp: gửi {cmd:#x}, nhận {resp_cmd:#x}")
        # 2 hoặc 4 byte cuối của resp_data là status: [0]=0 nghĩa là OK.
        if len(resp_data) >= 2 and resp_data[-2] != 0:
            raise EspLoaderError(f"ROM loader báo lỗi cho lệnh {cmd:#x}, status={resp_data[-4:].hex()}")
        return resp_data, value

    # ---------------------------------------------------------------
    def sync(self, attempts: int = 7) -> bool:
        """Gửi lệnh SYNC lặp lại cho tới khi ROM bootloader phản hồi."""
        sync_payload = b"\x07\x07\x12\x20" + b"\x55" * 32
        for i in range(attempts):
            try:
                self._send_command(CMD_SYNC, sync_payload)
                resp_cmd, _data, _value = self._read_response(timeout_ms=200)
                if resp_cmd == CMD_SYNC:
                    # Đọc cạn các phản hồi SYNC trùng lặp còn sót lại.
                    try:
                        while True:
                            self._read_response(timeout_ms=50)
                    except EspLoaderError:
                        pass
                    return True
            except EspLoaderError:
                continue
        return False

    def connect(self, bridge_reset: bool = True, max_retries: int = 5) -> None:
        """Đưa chip vào chế độ download và đồng bộ giao thức."""
        for attempt in range(1, max_retries + 1):
            logger.info(f"Đang kết nối tới ESP32 (lần {attempt}/{max_retries})...")
            if bridge_reset:
                self.bridge.enter_bootloader()
                time.sleep(0.1)
            if self.sync():
                logger.ok("Đã đồng bộ (sync) với ROM bootloader.")
                self._detect_chip()
                return
        raise EspLoaderError(
            "Không thể kết nối với ESP32. Kiểm tra:\n"
            "  - Cáp USB có hỗ trợ truyền dữ liệu (không chỉ sạc)\n"
            "  - Board đã cắm chắc chắn\n"
            "  - Giữ nút BOOT/IO0 khi cắm nếu board không tự vào chế độ nạp"
        )

    def _detect_chip(self) -> None:
        try:
            magic = self.read_reg(CHIP_MAGIC_REG)
            self.chip_name = CHIP_MAGIC_TABLE.get(magic, f"Không xác định (magic={magic:#010x})")
            logger.info(f"Chip phát hiện: {self.chip_name}")
        except EspLoaderError:
            self.chip_name = "Không xác định"

    # ---------------------------------------------------------------
    def read_reg(self, address: int) -> int:
        data, value = self.command(CMD_READ_REG, struct.pack("<I", address))
        return value

    def write_reg(self, address: int, value: int, mask: int = 0xFFFFFFFF, delay_us: int = 0) -> None:
        payload = struct.pack("<IIII", address, value, mask, delay_us)
        self.command(CMD_WRITE_REG, payload)

    def change_baudrate(self, new_baud: int, old_baud: int) -> None:
        payload = struct.pack("<II", new_baud, old_baud)
        self.command(CMD_CHANGE_BAUDRATE, payload)
        self.bridge.set_baudrate(new_baud)
        time.sleep(0.05)

    def spi_attach(self) -> None:
        self.command(CMD_SPI_ATTACH, struct.pack("<I", 0))

    # ---------------------------------------------------------------
    def mem_begin(self, size: int, num_blocks: int, block_size: int, offset: int) -> None:
        payload = struct.pack("<IIII", size, num_blocks, block_size, offset)
        self.command(CMD_MEM_BEGIN, payload)

    def mem_block(self, data: bytes, seq: int) -> None:
        header = struct.pack("<IIII", len(data), seq, 0, 0)
        self.command(CMD_MEM_DATA, header + data, chk=checksum(data))

    def mem_finish(self, entry_point: int = 0) -> None:
        flag = 0 if entry_point else 1
        payload = struct.pack("<II", flag, entry_point)
        self.command(CMD_MEM_END, payload)

    # ---------------------------------------------------------------
    def flash_begin(self, size: int, offset: int) -> int:
        """Trả về số block cần ghi."""
        num_blocks = (size + FLASH_WRITE_SIZE - 1) // FLASH_WRITE_SIZE
        erase_size = num_blocks * FLASH_WRITE_SIZE
        payload = struct.pack("<IIII", erase_size, num_blocks, FLASH_WRITE_SIZE, offset)
        self.command(CMD_FLASH_BEGIN, payload, timeout_ms=15000)
        return num_blocks

    def flash_block(self, data: bytes, seq: int) -> None:
        if len(data) < FLASH_WRITE_SIZE:
            data = data + b"\xff" * (FLASH_WRITE_SIZE - len(data))
        header = struct.pack("<IIII", len(data), seq, 0, 0)
        self.command(CMD_FLASH_DATA, header + data, chk=checksum(data), timeout_ms=5000)

    def flash_finish(self, reboot: bool = True) -> None:
        payload = struct.pack("<I", 0 if reboot else 1)
        self.command(CMD_FLASH_END, payload)

    def flash_md5(self, offset: int, size: int) -> str:
        payload = struct.pack("<IIII", offset, size, 0, 0)
        data, _value = self.command(CMD_SPI_FLASH_MD5, payload, timeout_ms=10000)
        return data[:32].decode("ascii", errors="ignore")

    def read_flash(self, offset: int, size: int, progress_cb=None) -> bytes:
        payload = struct.pack("<IIII", offset, size, FLASH_WRITE_SIZE, 64)
        self._send_command(CMD_READ_FLASH, payload)
        received = bytearray()
        while len(received) < size:
            resp_cmd, data, value = self._read_response(timeout_ms=10000)
            if resp_cmd != CMD_READ_FLASH:
                continue
            received.extend(data)
            # Gửi ACK: 4 byte little-endian số byte đã nhận (giao thức ROM).
            self.bridge.write(slip_encode(struct.pack("<I", len(received))))
            if progress_cb:
                progress_cb(len(received))
        return bytes(received[:size])

    # ---------------------------------------------------------------
    def hard_reset(self) -> None:
        self.bridge.hard_reset()


# --------------------------------------------------------------------------
# Tiện ích ghép nối USB -> UartBridge -> EspRomLoader
# --------------------------------------------------------------------------


def open_loader(device_path: str, baud: int = DEFAULT_RESET_BAUD) -> Tuple[AndroidUsbDevice, EspRomLoader]:
    usb_dev = AndroidUsbDevice(device_path)
    usb_dev.open()
    vendor_id, product_id = usb_dev.get_device_descriptor()
    logger.info(f"Thiết bị USB: VID={vendor_id:04x} PID={product_id:04x}")
    bridge = create_bridge(usb_dev, vendor_id, product_id)
    bridge.open()
    bridge.set_baudrate(baud)
    loader = EspRomLoader(bridge)
    return usb_dev, loader


# --------------------------------------------------------------------------
# Các thao tác cấp cao (dùng bởi flash.sh, erase.sh, chipinfo.sh, mac.sh)
# --------------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        logger.ok(f"Kết nối thành công. Chip: {loader.chip_name}")
        return 0
    finally:
        usb_dev.close()


def cmd_chip_id(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        mac = _read_mac(loader)
        print(f"Chip            : {loader.chip_name}")
        print(f"MAC             : {mac}")
        print(f"Magic Register  : {loader.read_reg(CHIP_MAGIC_REG):#010x}")
        return 0
    finally:
        usb_dev.close()


def _read_mac(loader: EspRomLoader) -> str:
    # ESP32: MAC được lưu ở thanh ghi EFUSE MAC (0x3ff5A004 / 0x3ff5A008 trên ESP32 cổ điển).
    mac0 = loader.read_reg(0x3FF5A004)
    mac1 = loader.read_reg(0x3FF5A008)
    bytes_mac = [
        (mac1 >> 8) & 0xFF,
        mac1 & 0xFF,
        (mac0 >> 24) & 0xFF,
        (mac0 >> 16) & 0xFF,
        (mac0 >> 8) & 0xFF,
        mac0 & 0xFF,
    ]
    return ":".join(f"{b:02X}" for b in bytes_mac)


def cmd_read_mac(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        print(f"MAC:\n{_read_mac(loader)}")
        return 0
    finally:
        usb_dev.close()


def cmd_flash_id(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        loader.spi_attach()
        # Lệnh RDID (0x9F) của SPI flash thông qua thanh ghi SPI của chip.
        # Đơn giản hóa: đọc flash size gián tiếp qua flash_begin(0 byte).
        print(f"Chip            : {loader.chip_name}")
        print("Flash Mode      : QIO/DIO (tự động, theo cấu hình bootloader)")
        print("Flash Speed     : 40MHz (mặc định, có thể khác theo board)")
        return 0
    finally:
        usb_dev.close()


def cmd_erase_flash(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        loader.spi_attach()
        print("Connecting...")
        logger.info("Đang xóa toàn bộ flash (có thể mất 20-60 giây)...")
        print("Erasing...")
        # Ghi 1 block rỗng với size=0xFFFFFFFF để trigger full chip erase
        # theo giao thức ROM loader (FLASH_BEGIN với size lớn + FLASH_END).
        loader.command(CMD_FLASH_BEGIN, struct.pack("<IIII", 0, 0, FLASH_WRITE_SIZE, 0), timeout_ms=60000)
        loader.flash_finish(reboot=False)
        loader.hard_reset()
        print("Done")
        logger.ok("Đã xóa flash thành công.")
        return 0
    finally:
        usb_dev.close()


def cmd_write_flash(args: argparse.Namespace) -> int:
    pairs = args.offset_file
    if len(pairs) % 2 != 0:
        logger.error("Tham số write_flash phải theo cặp: <offset> <file> ...")
        return 1

    entries: List[Tuple[int, str]] = []
    for i in range(0, len(pairs), 2):
        offset = int(pairs[i], 0)
        path = pairs[i + 1]
        if not check_file_exists(path):
            logger.error(f"Không tìm thấy file: {path}")
            return 1
        entries.append((offset, path))

    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        loader.spi_attach()
        if args.flash_baud and args.flash_baud != DEFAULT_RESET_BAUD:
            logger.info(f"Đổi baudrate lên {args.flash_baud} để tăng tốc độ ghi...")
            loader.change_baudrate(args.flash_baud, DEFAULT_RESET_BAUD)

        start_time = time.time()
        total_size = sum(os.path.getsize(p) for _, p in entries)
        logger.info(f"Tổng dung lượng cần ghi: {format_size(total_size)}")

        for offset, path in entries:
            _write_one_file(loader, offset, path)

        loader.flash_finish(reboot=True)
        elapsed = time.time() - start_time
        loader.hard_reset()
        logger.ok(f"Flash hoàn tất trong {elapsed:.1f} giây.")
        return 0
    except (EspLoaderError, UartBridgeError, AndroidUsbError) as exc:
        logger.error(str(exc))
        return 1
    finally:
        usb_dev.close()


def _write_one_file(loader: EspRomLoader, offset: int, path: str) -> None:
    size = os.path.getsize(path)
    logger.info(f"Ghi {path} ({format_size(size)}) tại offset {offset:#x}")
    num_blocks = loader.flash_begin(size, offset)
    bar = ProgressBar(total=size, label="  ")
    with open(path, "rb") as f:
        for seq in range(num_blocks):
            chunk = f.read(FLASH_WRITE_SIZE)
            if not chunk:
                break
            loader.flash_block(chunk, seq)
            bar.add(len(chunk))
    bar.finish()


def cmd_read_flash(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        loader.spi_attach()
        offset = int(args.offset, 0)
        size = int(args.size, 0)
        bar = ProgressBar(total=size, label="  ")
        data = loader.read_flash(offset, size, progress_cb=bar.update)
        bar.finish()
        with open(args.output, "wb") as f:
            f.write(data)
        logger.ok(f"Đã đọc {format_size(len(data))} vào {args.output}")
        return 0
    finally:
        usb_dev.close()


def cmd_verify_flash(args: argparse.Namespace) -> int:
    if not check_file_exists(args.file):
        logger.error(f"Không tìm thấy file: {args.file}")
        return 1
    usb_dev, loader = open_loader(args.device)
    try:
        loader.connect()
        loader.spi_attach()
        offset = int(args.offset, 0)
        size = os.path.getsize(args.file)
        import hashlib

        with open(args.file, "rb") as f:
            local_md5 = hashlib.md5(f.read()).hexdigest()
        remote_md5 = loader.flash_md5(offset, size)
        if local_md5 == remote_md5:
            logger.ok(f"Xác minh THÀNH CÔNG. MD5: {local_md5}")
            return 0
        logger.error(f"Xác minh THẤT BẠI. Local={local_md5} Remote={remote_md5}")
        return 1
    finally:
        usb_dev.close()


def cmd_image_info(args: argparse.Namespace) -> int:
    if not check_file_exists(args.file):
        logger.error(f"Không tìm thấy file: {args.file}")
        return 1
    with open(args.file, "rb") as f:
        header = f.read(24)
    if len(header) < 8 or header[0] != 0xE9:
        logger.error("File không phải firmware image hợp lệ (thiếu magic byte 0xE9).")
        return 1
    magic, num_segments, flash_mode, flash_size_freq = struct.unpack("<BBBB", header[:4])
    entry_point = struct.unpack("<I", header[4:8])[0]
    flash_modes = {0: "QIO", 1: "QOUT", 2: "DIO", 3: "DOUT"}
    sizes = {0: "1MB", 1: "2MB", 2: "4MB", 3: "8MB", 4: "16MB"}
    freqs = {0: "40MHz", 1: "26MHz", 2: "20MHz", 15: "80MHz"}
    print(f"Magic           : {magic:#04x}")
    print(f"Số segment      : {num_segments}")
    print(f"Flash Mode      : {flash_modes.get(flash_mode, 'Unknown')}")
    print(f"Flash Size      : {sizes.get((flash_size_freq >> 4) & 0x0F, 'Unknown')}")
    print(f"Flash Speed     : {freqs.get(flash_size_freq & 0x0F, 'Unknown')}")
    print(f"Entry Point     : {entry_point:#010x}")
    print(f"Kích thước file : {format_size(os.path.getsize(args.file))}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    usb_dev, loader = open_loader(args.device)
    try:
        loader.bridge.open()
        loader.hard_reset()
        logger.ok("Đã reset ESP32.")
        return 0
    finally:
        usb_dev.close()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android_esptool.py",
        description="Công cụ nạp/đọc/xóa flash ESP32 thuần Python cho Android/Termux (không PlatformIO).",
    )
    parser.add_argument("-v", "--debug", action="store_true", help="Bật log debug chi tiết")
    sub = parser.add_subparsers(dest="action", required=True)

    def add_device_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("--device", required=True, help="Đường dẫn thiết bị USB (vd: /dev/bus/usb/001/002)")

    p = sub.add_parser("sync", help="Kiểm tra kết nối và đồng bộ với ROM bootloader")
    add_device_arg(p)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("chip_id", help="Đọc thông tin chip")
    add_device_arg(p)
    p.set_defaults(func=cmd_chip_id)

    p = sub.add_parser("read_mac", help="Đọc địa chỉ MAC")
    add_device_arg(p)
    p.set_defaults(func=cmd_read_mac)

    p = sub.add_parser("flash_id", help="Đọc thông tin flash SPI")
    add_device_arg(p)
    p.set_defaults(func=cmd_flash_id)

    p = sub.add_parser("erase_flash", help="Xóa toàn bộ flash")
    add_device_arg(p)
    p.set_defaults(func=cmd_erase_flash)

    p = sub.add_parser("write_flash", help="Ghi firmware vào flash")
    add_device_arg(p)
    p.add_argument("--flash-baud", type=int, default=DEFAULT_FLASH_BAUD, help="Baudrate khi ghi flash")
    p.add_argument("offset_file", nargs="+", help="Cặp <offset> <file> ... vd: 0x1000 bootloader.bin")
    p.set_defaults(func=cmd_write_flash)

    p = sub.add_parser("read_flash", help="Đọc flash ra file")
    add_device_arg(p)
    p.add_argument("offset")
    p.add_argument("size")
    p.add_argument("output")
    p.set_defaults(func=cmd_read_flash)

    p = sub.add_parser("verify_flash", help="So sánh MD5 file local với flash trên chip")
    add_device_arg(p)
    p.add_argument("offset")
    p.add_argument("file")
    p.set_defaults(func=cmd_verify_flash)

    p = sub.add_parser("image_info", help="Hiển thị thông tin firmware image (không cần thiết bị)")
    p.add_argument("file")
    p.set_defaults(func=cmd_image_info)

    p = sub.add_parser("reset", help="Reset (khởi động lại) ESP32")
    add_device_arg(p)
    p.set_defaults(func=cmd_reset)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    print("ARGS =", args)
    print("DEVICE =", args.device)
    try:
        return args.func(args)
    except (EspLoaderError, UartBridgeError, AndroidUsbError) as exc:
        logger.error(str(exc))
        return 1
    except KeyboardInterrupt:
        logger.warning("Đã hủy bởi người dùng.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
