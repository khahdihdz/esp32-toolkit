#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
esp_loader.py
=============
Triển khai giao thức nạp ROM bootloader của ESP32 (đóng khung SLIP +
lệnh nhị phân), hoàn toàn bằng Python thuần, không phụ thuộc
esptool.py gốc, không dùng pySerial.

Giao thức bên dưới (SLIP framing, mã lệnh, checksum, cách tính magic
number nhận diện chip) là giao thức công khai do Espressif tài liệu
hóa và được esptool.py mã nguồn mở triển khai — không phải bí mật
thương mại.
"""

from __future__ import annotations

import struct
import sys
import time
import os
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
from usb_bridge import UartBridge, UartBridgeError  # noqa: E402
from utils import retry  # noqa: E402

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

# Bảng nhận diện chip qua giá trị "magic number" đọc từ CHIP_MAGIC_REG.
# Lấy từ tài liệu công khai của esptool (chip_detect_magic_value).
CHIP_MAGIC_TABLE = {
    0x00F01D83: "ESP32",
    0x000007C6: "ESP32-S2",
    0x00000009: "ESP32-S3",
    0x6921506F: "ESP32-C3",
    0x1B31506F: "ESP32-C3 (rev0)",
    0x2CA1806F: "ESP32-C2",
    0x0DA1806F: "ESP32-C6",
    0x00000005: "ESP32-H2",
    0xFFF0C101: "ESP8266",
}

DEFAULT_RESET_BAUD = 115200
DEFAULT_FLASH_BAUD = 460800

# Địa chỉ thanh ghi EFUSE chứa MAC mặc định trên ESP32 dòng cổ điển.
MAC_EFUSE_REG_0 = 0x3FF5A004
MAC_EFUSE_REG_1 = 0x3FF5A008


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
    """Bộ giải mã SLIP dạng stream, dùng để đọc phản hồi từ ROM loader."""

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
    """Giao tiếp với ROM bootloader của ESP32 qua UartBridge, dùng SLIP nhị phân."""

    def __init__(self, bridge: UartBridge) -> None:
        self.bridge = bridge
        self._decoder = SlipDecoder()
        self.chip_name = "Unknown"
        self.chip_magic = 0

    # ---------------------------------------------------------------
    def _send_command(self, cmd: int, data: bytes = b"", chk: int = 0) -> None:
        header = struct.pack("<BBHI", 0x00, cmd, len(data), chk)
        self.bridge.write(slip_encode(header + data))

    def _read_response(self, timeout_ms: int = 3000) -> Tuple[int, bytes, int]:
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
        raise EspLoaderError("Het thoi gian cho phan hoi tu ROM bootloader (timeout).")

    @retry(max_attempts=3, delay_seconds=0.3, exceptions=(EspLoaderError,))
    def command(self, cmd: int, data: bytes = b"", chk: int = 0, timeout_ms: int = 3000) -> Tuple[bytes, int]:
        self._send_command(cmd, data, chk)
        resp_cmd, resp_data, value = self._read_response(timeout_ms)
        if resp_cmd != cmd:
            raise EspLoaderError(f"Lenh phan hoi khong khop: gui {cmd:#x}, nhan {resp_cmd:#x}")
        if len(resp_data) >= 2 and resp_data[-2] != 0:
            raise EspLoaderError(f"ROM loader bao loi cho lenh {cmd:#x}, status={resp_data[-4:].hex()}")
        return resp_data, value

    # ---------------------------------------------------------------
    def sync(self, attempts: int = 7) -> bool:
        """Gửi lệnh SYNC lặp lại cho tới khi ROM bootloader phản hồi."""
        sync_payload = b"\x07\x07\x12\x20" + b"\x55" * 32
        for _ in range(attempts):
            try:
                self._send_command(CMD_SYNC, sync_payload)
                resp_cmd, _data, _value = self._read_response(timeout_ms=200)
                if resp_cmd == CMD_SYNC:
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
            logger.info(f"Dang ket noi toi ESP32 (lan {attempt}/{max_retries})...")
            if bridge_reset:
                self.bridge.enter_bootloader()
                time.sleep(0.1)
            if self.sync():
                logger.ok("Da dong bo (sync) voi ROM bootloader.")
                self._detect_chip()
                return
        raise EspLoaderError(
            "Khong the ket noi voi ESP32. Kiem tra:\n"
            "  - Cap USB co ho tro truyen du lieu (khong chi sac)\n"
            "  - Board da cam chac chan\n"
            "  - Giu nut BOOT/IO0 khi cam neu board khong tu vao che do nap"
        )

    def _detect_chip(self) -> None:
        try:
            magic = self.read_reg(CHIP_MAGIC_REG)
            self.chip_magic = magic
            self.chip_name = CHIP_MAGIC_TABLE.get(magic, f"Khong xac dinh (magic={magic:#010x})")
            logger.info(f"Chip phat hien: {self.chip_name}")
        except EspLoaderError:
            self.chip_name = "Khong xac dinh"

    # ---------------------------------------------------------------
    def read_reg(self, address: int) -> int:
        _data, value = self.command(CMD_READ_REG, struct.pack("<I", address))
        return value

    def write_reg(self, address: int, value: int, mask: int = 0xFFFFFFFF, delay_us: int = 0) -> None:
        payload = struct.pack("<IIII", address, value, mask, delay_us)
        self.command(CMD_WRITE_REG, payload)

    def change_baudrate(self, new_baud: int, old_baud: int) -> None:
        payload = struct.pack("<II", new_baud, old_baud)
        self.command(CMD_CHANGE_BAUDRATE, payload)
        self.bridge.set_baud(new_baud)
        time.sleep(0.05)

    def spi_attach(self) -> None:
        self.command(CMD_SPI_ATTACH, struct.pack("<I", 0))

    # ---------------------------------------------------------------
    def flash_begin(self, size: int, offset: int, write_size: int = FLASH_WRITE_SIZE) -> int:
        """Trả về số block cần ghi."""
        num_blocks = (size + write_size - 1) // write_size
        erase_size = num_blocks * write_size
        payload = struct.pack("<IIII", erase_size, num_blocks, write_size, offset)
        self.command(CMD_FLASH_BEGIN, payload, timeout_ms=15000)
        return num_blocks

    def flash_block(self, data: bytes, seq: int, write_size: int = FLASH_WRITE_SIZE) -> None:
        if len(data) < write_size:
            data = data + b"\xff" * (write_size - len(data))
        header = struct.pack("<IIII", len(data), seq, 0, 0)
        self.command(CMD_FLASH_DATA, header + data, chk=checksum(data), timeout_ms=5000)

    def flash_finish(self, reboot: bool = True) -> None:
        payload = struct.pack("<I", 0 if reboot else 1)
        self.command(CMD_FLASH_END, payload)

    def flash_md5(self, offset: int, size: int) -> str:
        # QUAN TRONG: xa het byte con sot tren UART va reset bo giai ma
        # SLIP truoc khi goi. Ly do: neu lenh flash_md5 CU (vd: file lon,
        # ROM tinh MD5 mat nhieu thoi gian, sat gioi han timeout va bi
        # retry) co phan hoi den TRE, no co the con nam sot trong buffer.
        # Vi flash_md5 goi lien tiep nhieu lan (moi file mot lan) va DUNG
        # CHUNG ma lenh CMD_SPI_FLASH_MD5, mot phan hoi cu sot lai se bi
        # nham la phan hoi cua file hien tai — gay verify SAI (vd: 2 file
        # khac offset/kich thuoc lai bao ve cung mot MD5).
        # flush() don thuan chi doi 50ms khong thay du lieu la coi nhu
        # sach — neu phan hoi TRE cua lenh truoc toi ngay SAU cua so do,
        # no van lot qua va bi lenh nay nuot nham (hai lenh deu dung
        # chung ma CMD_SPI_FLASH_MD5 nen khong phan biet duoc). De giam
        # rui ro, doi BA lan doc trong LIEN TIEP (co nghi giua) truoc
        # khi coi la da sach hang doi. Dong log [DRAIN] o day de xac
        # nhan ban vin nay dang thuc su chay (khong bi __pycache__ cu
        # ghi de).
        logger.info(f"[DRAIN] Dang xa dem UART truoc khi doc MD5 (offset={offset:#x})...")
        try:
            for _ in range(3):
                self.bridge.flush()
                time.sleep(0.2)
        except Exception:
            pass
        self._decoder = SlipDecoder()

        payload = struct.pack("<IIII", offset, size, 0, 0)
        data, _value = self.command(CMD_SPI_FLASH_MD5, payload, timeout_ms=10000)
        return data[:32].decode("ascii", errors="ignore")

    def read_flash(self, offset: int, size: int, progress_cb=None, write_size: int = FLASH_WRITE_SIZE) -> bytes:
        payload = struct.pack("<IIII", offset, size, write_size, 64)
        self._send_command(CMD_READ_FLASH, payload)
        received = bytearray()
        while len(received) < size:
            resp_cmd, data, _value = self._read_response(timeout_ms=10000)
            if resp_cmd != CMD_READ_FLASH:
                continue
            received.extend(data)
            # ACK: 4 byte little-endian số byte đã nhận (giao thức ROM).
            self.bridge.write(slip_encode(struct.pack("<I", len(received))))
            if progress_cb:
                progress_cb(len(received))
        return bytes(received[:size])

    def erase_flash(self, write_size: int = FLASH_WRITE_SIZE) -> None:
        """Xóa toàn bộ chip: FLASH_BEGIN với size=0 num_blocks=0 rồi FLASH_END không reboot."""
        self.command(CMD_FLASH_BEGIN, struct.pack("<IIII", 0, 0, write_size, 0), timeout_ms=60000)
        self.flash_finish(reboot=False)

    def read_mac(self) -> str:
        mac0 = self.read_reg(MAC_EFUSE_REG_0)
        mac1 = self.read_reg(MAC_EFUSE_REG_1)
        mac_bytes = [
            (mac1 >> 8) & 0xFF,
            mac1 & 0xFF,
            (mac0 >> 24) & 0xFF,
            (mac0 >> 16) & 0xFF,
            (mac0 >> 8) & 0xFF,
            mac0 & 0xFF,
        ]
        return ":".join(f"{b:02X}" for b in mac_bytes)

    # ---------------------------------------------------------------
    def hard_reset(self) -> None:
        self.bridge.hard_reset()
