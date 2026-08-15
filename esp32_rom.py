#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ESP32 ROM serial bootloader protocol
====================================

ESP32 USB Flasher v3
HONOR X7d / Termux / USB OTG
CP210x USB-UART -> ESP32 ROM Bootloader

Chức năng:
- SLIP protocol
- SYNC
- READ_REG / WRITE_REG
- Detect ESP32 classic
- SPI_ATTACH
- Đọc JEDEC Flash ID
- Detect dung lượng Flash
- FLASH_BEGIN / FLASH_DATA / FLASH_END
- CHANGE_BAUD
- READ_FLASH_SLOW
- Erase bằng FLASH_BEGIN + FLASH_DATA
- Chip erase

Lưu ý:
- ESP32 classic sử dụng SPI0 cho SPI flash tích hợp.
- SPI0 base = 0x3FF43000.
- SPI1 base = 0x3FF42000, không dùng để đọc flash boot.
"""

from __future__ import annotations

import struct
import time
import re

from slip import slip_encode, SlipDecoder
from cp210x import CP210x
from usbdevfs import USBTimeoutError


# ============================================================
# ESP32 ROM COMMANDS
# ============================================================

FLASH_BEGIN = 0x02
FLASH_DATA = 0x03
FLASH_END = 0x04

MEM_BEGIN = 0x05
MEM_END = 0x06
MEM_DATA = 0x07

SYNC = 0x08
WRITE_REG = 0x09
READ_REG = 0x0A

SPI_SET_PARAMS = 0x0B
SPI_ATTACH = 0x0D
READ_FLASH_SLOW = 0x0E
CHANGE_BAUD = 0x0F

SPI_FLASH_MD5 = 0x13

ERASE_FLASH = 0xD0


# ============================================================
# ESP32 ROM PROTOCOL
# ============================================================

CHECKSUM_MAGIC = 0xEF

FLASH_WRITE_SIZE = 0x400
FLASH_SECTOR = 0x1000


# ============================================================
# ESP32 CLASSIC CHIP DETECTION
# ============================================================

MAGIC_ADDR = 0x40001000
ESP32_MAGIC = 0x00F01D83


# ============================================================
# ESP32 CLASSIC SPI0 REGISTERS
# ============================================================

# QUAN TRỌNG:
#
# ESP32 classic:
#   SPI0 = 0x3FF43000  -> SPI flash
#   SPI1 = 0x3FF42000
#
# Bản trước dùng 0x3FF42000 nên thực chất thao tác SPI1.
# Kết quả JEDEC thường trở thành FF FF FF.
#
SPI_REG_BASE = 0x3FF43000

SPI_CMD_REG = SPI_REG_BASE + 0x00

SPI_USR_REG = SPI_REG_BASE + 0x1C
SPI_USR1_REG = SPI_REG_BASE + 0x20
SPI_USR2_REG = SPI_REG_BASE + 0x24

SPI_MOSI_DLEN_REG = SPI_REG_BASE + 0x28
SPI_MISO_DLEN_REG = SPI_REG_BASE + 0x2C

SPI_W0_REG = SPI_REG_BASE + 0x80


# ============================================================
# SPI REGISTER BITS
# ============================================================

# SPI_CMD_REG
SPI_CMD_USR = 1 << 18


# SPI_USR_REG
SPI_USR_COMMAND = 1 << 31
SPI_USR_MISO = 1 << 28
SPI_USR_MOSI = 1 << 27


# SPI_USR2_REG
#
# ESP32:
# COMMAND_LEN [31:28]
# COMMAND     [7:0]
#
SPI_USR2_COMMAND_LEN_SHIFT = 28


# ============================================================
# SPI FLASH COMMANDS
# ============================================================

SPIFLASH_RDID = 0x9F


# ============================================================
# FLASH SIZE TABLE
# ============================================================

# JEDEC capacity byte chuẩn JEDEC:
#
# 0x14 = 1 MB
# 0x15 = 2 MB
# 0x16 = 4 MB
# 0x17 = 8 MB
# 0x18 = 16 MB
# 0x19 = 32 MB
# 0x20 = 64 MB
#
# Không tự động chấp nhận mọi giá trị 0..31.

JEDEC_CAPACITY_MAP = {
    0x10: 128 * 1024,
    0x11: 256 * 1024,
    0x12: 512 * 1024,
    0x13: 1024 * 1024,
    0x14: 2 * 1024 * 1024,
    0x15: 2 * 1024 * 1024,
    0x16: 4 * 1024 * 1024,
    0x17: 8 * 1024 * 1024,
    0x18: 16 * 1024 * 1024,
    0x19: 32 * 1024 * 1024,
    0x20: 64 * 1024 * 1024,
}


# ============================================================
# EXCEPTIONS
# ============================================================

class ROMError(RuntimeError):
    pass


# ============================================================
# CHECKSUM
# ============================================================

def checksum(data: bytes, state: int = CHECKSUM_MAGIC) -> int:
    """
    Checksum XOR theo giao thức ESP32 ROM.
    """

    for b in data:
        state ^= b

    return state


# ============================================================
# ESP32 ROM
# ============================================================

class ESP32ROM:

    def __init__(
        self,
        uart: CP210x,
        baud: int = 115200,
        debug: bool = False,
    ):
        self.uart = uart
        self.baud = baud
        self.debug = debug

        self.decoder = SlipDecoder()

        self.rx = b""

        self.magic = None

        # Frame đã decode nhưng chưa được command() sử dụng.
        #
        # Quan trọng:
        # Một BULK IN có thể chứa nhiều SLIP frame.
        # Không được bỏ các frame dư.
        self.frame_queue = []

    # ========================================================
    # LOG
    # ========================================================

    def _log(self, text: str):
        if self.debug:
            print(text, flush=True)

    # ========================================================
    # READ ONE SLIP FRAME
    # ========================================================

    def _read_frame(self, timeout: float = 3.0) -> bytes:
        """
        Đọc một SLIP frame.

        USB Bulk IN được poll nhiều lần.
        ETIMEDOUT/EAGAIN chỉ có nghĩa là chưa có dữ liệu
        trong một lần poll ngắn.
        """

        # Một số unit test/khởi tạo nhẹ có thể tạo object bằng __new__
        # nên frame_queue chưa tồn tại. Khởi tạo lười để không làm hỏng
        # đường đọc USB thực tế.
        if not hasattr(self, "frame_queue"):
            self.frame_queue = []

        if self.frame_queue:
            return self.frame_queue.pop(0)

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            try:
                chunk = self.uart.bulk_read(
                    4096,
                    250,
                )

            except USBTimeoutError:
                continue

            if not chunk:
                continue

            frames = self.decoder.feed(chunk)

            if frames:

                self.frame_queue.extend(frames)

                return self.frame_queue.pop(0)

        raise ROMError(
            "Timeout: không nhận được SLIP response từ ESP32."
        )

    # ========================================================
    # COMMAND
    # ========================================================

    def command(
        self,
        op,
        data=b"",
        chk=0,
        timeout=3.0,
        retries=1,
    ) -> tuple[int, bytes]:

        packet = struct.pack(
            "<BBHI",
            0,
            op,
            len(data),
            chk,
        ) + data

        encoded = slip_encode(packet)

        last_error = None

        for attempt in range(retries + 1):

            self._log(
                "SLIP TX: " +
                encoded[:64].hex(" ")
            )

            self.uart.bulk_write(
                encoded,
                timeout_ms=max(
                    1000,
                    int(timeout * 1000),
                ),
            )

            try:

                for _ in range(20):

                    response = self._read_frame(timeout)

                    self._log(
                        "SLIP RX: " +
                        response[:64].hex(" ")
                    )

                    if len(response) < 8:
                        continue

                    direction, rop, length, value = struct.unpack(
                        "<BBHI",
                        response[:8],
                    )

                    if direction != 1:
                        continue

                    if rop != op:
                        continue

                    payload = response[
                        8:8 + length
                    ]

                    if len(payload) < length:
                        raise ROMError(
                            f"Response 0x{rop:02X} "
                            f"thiếu payload."
                        )

                    return value, payload

                raise ROMError(
                    f"Không nhận được phản hồi khớp "
                    f"cho lệnh 0x{op:02X}."
                )

            except ROMError as exc:

                last_error = exc

                if attempt < retries:

                    self._log(
                        f"[CẢNH BÁO] Lệnh "
                        f"0x{op:02X} không có phản hồi, "
                        f"thử lại..."
                    )

                    time.sleep(0.05)

                    continue

                break

        raise ROMError(
            f"Timeout: không nhận được phản hồi "
            f"SLIP từ ESP32 cho lệnh "
            f"0x{op:02X} "
            f"(chờ {timeout:.1f}s, "
            f"đã thử {retries + 1} lần). "
            f"Chi tiết: {last_error}"
        )

    # ========================================================
    # CHECK RESPONSE STATUS
    # ========================================================

    def check(
        self,
        op,
        data=b"",
        chk=0,
        timeout=3.0,
        expected=0,
        retries=1,
    ):

        value, payload = self.command(
            op,
            data,
            chk,
            timeout,
            retries=retries,
        )

        if len(payload) < expected + 4:
            raise ROMError(
                f"Response command 0x{op:02X} "
                f"quá ngắn."
            )

        status = payload[
            expected:expected + 4
        ]

        if status[:2] != b"\x00\x00":

            raise ROMError(
                f"ESP32 ROM báo lỗi command "
                f"0x{op:02X}: "
                f"{status.hex()}"
            )

        return value, payload[:expected]

    # ========================================================
    # DRAIN USB INPUT
    # ========================================================

    def _drain_input(self, seconds=0.20):

        end = time.monotonic() + seconds

        while time.monotonic() < end:

            try:
                self.uart.bulk_read(
                    4096,
                    20,
                )

            except USBTimeoutError:
                pass

        self.decoder = SlipDecoder()
        self.frame_queue.clear()

    # ========================================================
    # SYNC
    # ========================================================

    def sync(self, retries=5):

        last = None

        self._drain_input()

        sync_data = (
            b"\x07\x07\x12\x20" +
            b"\x55" * 32
        )

        for attempt in range(
            1,
            retries + 1,
        ):

            try:

                value, _ = self.command(
                    SYNC,
                    sync_data,
                    0,
                    1.5,
                    retries=0,
                )

                self._log(
                    f"SYNC RESPONSE VALUE: "
                    f"0x{value:08X}"
                )

                # ROM thường trả nhiều SYNC response.
                for _ in range(7):

                    try:
                        self._read_frame(0.08)

                    except ROMError:
                        break

                return True

            except Exception as exc:

                last = exc

                self._log(
                    f"[SYNC LẦN {attempt}/{retries}] "
                    f"{type(exc).__name__}: {exc}"
                )

                time.sleep(0.10)

                self._drain_input(0.05)

        raise ROMError(
            f"SYNC thất bại sau {retries} lần thử. "
            f"Chi tiết: {last}"
        )

    # ========================================================
    # RAW SYNC
    # ========================================================

    def sync_raw(self):

        self._drain_input()

        data = (
            b"\x07\x07\x12\x20" +
            b"\x55" * 32
        )

        value, payload = self.command(
            SYNC,
            data,
            0,
            2.0,
            retries=0,
        )

        print(
            f"[THÀNH CÔNG] SYNC RAW: "
            f"response value=0x{value:08X}",
            flush=True,
        )

        print(
            "[THÔNG TIN] Payload: " +
            payload.hex(" "),
            flush=True,
        )

        return value, payload

    # ========================================================
    # WRITE REG
    # ========================================================

    def write_reg(
        self,
        addr,
        value,
        mask=0xFFFFFFFF,
        delay_us=0,
    ):

        payload = struct.pack(
            "<IIII",
            addr,
            value,
            mask,
            delay_us,
        )

        self.command(
            WRITE_REG,
            payload,
            0,
            3.0,
            retries=1,
        )

    # ========================================================
    # READ REG
    # ========================================================

    def read_reg(self, addr):

        value, _ = self.command(
            READ_REG,
            struct.pack(
                "<I",
                addr,
            ),
            0,
            3.0,
        )

        return value

    # ========================================================
    # CHIP DETECTION
    # ========================================================

    def detect_chip(self):

        magic = self.read_reg(
            MAGIC_ADDR
        )

        self.magic = magic

        if magic != ESP32_MAGIC:

            raise ROMError(
                f"Chip magic "
                f"0x{magic:08X} "
                f"không khớp ESP32 classic "
                f"(0x{ESP32_MAGIC:08X})."
            )

        return "ESP32"

    # ========================================================
    # SPI ATTACH
    # ========================================================

    def spi_attach(self):

        arg = struct.pack(
            "<IBBBB",
            0,
            0,
            0,
            0,
            0,
        )

        self.check(
            SPI_ATTACH,
            arg,
            0,
            3.0,
            0,
        )

    # ========================================================
    # SPI USER COMMAND
    # ========================================================

    def run_spiflash_command(
        self,
        command,
        rx_bits=0,
    ):
        """
        Thực thi SPI USER command trên SPI0.

        Dùng cho:
            JEDEC RDID = 0x9F

        SPI0 của ESP32 classic:
            0x3FF43000

        command:
            opcode 8-bit

        rx_bits:
            số bit nhận từ SPI flash.
        """

        if not 0 <= command <= 0xFF:
            raise ROMError(
                f"SPI command không hợp lệ: "
                f"0x{command:X}"
            )

        if rx_bits < 0 or rx_bits > 32:
            raise ROMError(
                f"rx_bits không hợp lệ: "
                f"{rx_bits}"
            )

        # ----------------------------------------------------
        # Chờ USER command cũ kết thúc
        # ----------------------------------------------------

        cmd_reg = self.read_reg(
            SPI_CMD_REG
        )

        if cmd_reg & SPI_CMD_USR:

            deadline = (
                time.monotonic() + 1.0
            )

            while time.monotonic() < deadline:

                cmd_reg = self.read_reg(
                    SPI_CMD_REG
                )

                if not (
                    cmd_reg & SPI_CMD_USR
                ):
                    break

                time.sleep(0.001)

            else:

                raise ROMError(
                    "SPI USER command trước đó "
                    "vẫn đang chạy."
                )

        # ----------------------------------------------------
        # Cấu hình USER
        # ----------------------------------------------------

        usr = self.read_reg(
            SPI_USR_REG
        )

        usr &= ~(
            SPI_USR_COMMAND |
            SPI_USR_MISO |
            SPI_USR_MOSI
        )

        usr |= SPI_USR_COMMAND

        if rx_bits:
            usr |= SPI_USR_MISO

        self.write_reg(
            SPI_USR_REG,
            usr,
        )

        # ----------------------------------------------------
        # USER2
        #
        # COMMAND_LEN = 7 => 8 bit
        # COMMAND = opcode
        # ----------------------------------------------------

        usr2 = self.read_reg(
            SPI_USR2_REG
        )

        usr2 &= ~(
            0xF <<
            SPI_USR2_COMMAND_LEN_SHIFT
        )

        usr2 |= (
            7 <<
            SPI_USR2_COMMAND_LEN_SHIFT
        )

        usr2 &= ~0xFF
        usr2 |= command & 0xFF

        self.write_reg(
            SPI_USR2_REG,
            usr2,
        )

        # ----------------------------------------------------
        # MISO length
        # ----------------------------------------------------

        if rx_bits:

            self.write_reg(
                SPI_MISO_DLEN_REG,
                rx_bits - 1,
            )

        else:

            self.write_reg(
                SPI_MISO_DLEN_REG,
                0,
            )

        # ----------------------------------------------------
        # Xóa W0
        # ----------------------------------------------------

        self.write_reg(
            SPI_W0_REG,
            0,
        )

        # ----------------------------------------------------
        # Trigger USER command
        # ----------------------------------------------------

        cmd_reg = self.read_reg(
            SPI_CMD_REG
        )

        cmd_reg &= ~SPI_CMD_USR

        self.write_reg(
            SPI_CMD_REG,
            cmd_reg,
        )

        self.write_reg(
            SPI_CMD_REG,
            cmd_reg | SPI_CMD_USR,
        )

        # ----------------------------------------------------
        # Chờ hoàn tất
        # ----------------------------------------------------

        deadline = (
            time.monotonic() + 1.0
        )

        while time.monotonic() < deadline:

            cmd_reg = self.read_reg(
                SPI_CMD_REG
            )

            if not (
                cmd_reg & SPI_CMD_USR
            ):
                break

            time.sleep(0.001)

        else:

            raise ROMError(
                "Timeout khi thực thi "
                "SPI USER command."
            )

        # ----------------------------------------------------
        # Đọc W0
        # ----------------------------------------------------

        value = self.read_reg(
            SPI_W0_REG
        )

        self._log(
            f"[SPI] CMD=0x{command:02X} "
            f"RX_BITS={rx_bits} "
            f"W0=0x{value:08X}"
        )

        return value

    # ========================================================
    # READ JEDEC ID
    # ========================================================

    def read_flash_id(self):

        value = self.run_spiflash_command(
            SPIFLASH_RDID,
            rx_bits=24,
        )

        raw = value.to_bytes(
            4,
            "little",
        )

        manufacturer = raw[0]
        memory_type = raw[1]
        capacity = raw[2]

        self._log(
            "[SPI] JEDEC RAW: " +
            raw[:3].hex(" ")
        )

        return (
            manufacturer,
            memory_type,
            capacity,
        )

    # ========================================================
    # DETECT FLASH SIZE
    # ========================================================

    def detect_flash_size(self):

        manufacturer, memory_type, capacity = (
            self.read_flash_id()
        )

        jedec = bytes(
            [
                manufacturer,
                memory_type,
                capacity,
            ]
        )

        # ----------------------------------------------------
        # Không chấp nhận FF FF FF
        # ----------------------------------------------------

        if jedec == b"\xFF\xFF\xFF":

            raise ROMError(
                "JEDEC trả FF FF FF. "
                "SPI flash chưa trả dữ liệu."
            )

        # ----------------------------------------------------
        # Không chấp nhận 00 00 00
        # ----------------------------------------------------

        if jedec == b"\x00\x00\x00":

            raise ROMError(
                "JEDEC trả 00 00 00. "
                "SPI flash không phản hồi."
            )

        if capacity not in JEDEC_CAPACITY_MAP:

            raise ROMError(
                f"JEDEC capacity byte "
                f"không hỗ trợ: "
                f"0x{capacity:02X}"
            )

        size_bytes = JEDEC_CAPACITY_MAP[
            capacity
        ]

        return {
            "jedec_id":
                f"{manufacturer:02X} "
                f"{memory_type:02X} "
                f"{capacity:02X}",

            "manufacturer":
                manufacturer,

            "memory_type":
                memory_type,

            "capacity":
                capacity,

            "size_bytes":
                size_bytes,

            "size_mb":
                size_bytes /
                (1024 * 1024),
        }

    # ========================================================
    # SET FLASH PARAMETERS
    # ========================================================

    def set_flash_params(self, size):

        params = struct.pack(
            "<IIIIII",
            0,
            size,
            64 * 1024,
            FLASH_SECTOR,
            256,
            0xFFFF,
        )

        self.check(
            SPI_SET_PARAMS,
            params,
            0,
            3.0,
            0,
        )

    # ========================================================
    # FLASH BEGIN
    # ========================================================

    def flash_begin(
        self,
        size,
        offset,
    ):

        blocks = (
            size +
            FLASH_WRITE_SIZE - 1
        ) // FLASH_WRITE_SIZE

        erase = (
            (
                size +
                FLASH_SECTOR - 1
            ) //
            FLASH_SECTOR
        ) * FLASH_SECTOR

        params = struct.pack(
            "<IIII",
            erase,
            blocks,
            FLASH_WRITE_SIZE,
            offset,
        )

        timeout = max(
            20.0,
            60.0 *
            erase /
            1_000_000,
        )

        self.check(
            FLASH_BEGIN,
            params,
            0,
            timeout,
            0,
            retries=0,
        )

        return blocks

    # ========================================================
    # FLASH DATA
    # ========================================================

    def flash_data(
        self,
        data,
        seq,
        timeout=8.0,
    ):
        """
        Ghi đúng một block FLASH_DATA.

        Không retry FLASH_DATA tự động. Nếu ACK bị mất sau khi
        ESP32 đã ghi block, gửi lại cùng sequence có thể làm
        trạng thái ROM không còn đồng bộ.
        """

        if not data:
            raise ROMError("FLASH_DATA không được rỗng.")

        payload = (
            struct.pack(
                "<IIII",
                len(data),
                seq,
                0,
                0,
            )
            + data
        )

        self.check(
            FLASH_DATA,
            payload,
            checksum(data),
            timeout,
            0,
            retries=0,
        )

    # ========================================================
    # FLASH END
    # ========================================================

    def flash_end(
        self,
        reboot=True,
        timeout=10.0,
    ):
        """
        Gửi FLASH_END.

        reboot=True  -> word 0: reboot.
        reboot=False -> word 1: chạy user code.

        ROM-only flashing không bắt buộc phải gửi FLASH_END nếu
        host muốn giữ loader; v3 hiện verify MD5 trước rồi reset
        bằng DTR/RTS để tránh mất ACK cuối.
        """

        self.check(
            FLASH_END,
            struct.pack(
                "<I",
                int(not reboot),
            ),
            0,
            timeout,
            0,
            retries=0,
        )

    # ========================================================
    # SPI FLASH MD5
    # ========================================================

    def flash_md5(
        self,
        offset,
        size,
        timeout=None,
    ):
        """
        Tính MD5 trực tiếp trên vùng Flash bằng SPI_FLASH_MD5 (0x13).

        ESP32 ROM thường trả 32 byte ASCII hex.
        Stub Espressif có thể trả 16 byte raw MD5, hỗ trợ cả hai.
        """

        if offset < 0 or size <= 0:
            raise ValueError("offset/size MD5 không hợp lệ.")

        if timeout is None:
            timeout = max(
                3.0,
                8.0 * size / 1_000_000.0,
            )

        params = struct.pack(
            "<IIII",
            offset,
            size,
            0,
            0,
        )

        _, payload = self.command(
            SPI_FLASH_MD5,
            params,
            0,
            timeout,
            retries=0,
        )

        if len(payload) == 32:
            try:
                digest = payload.decode("ascii").lower()
            except UnicodeDecodeError as exc:
                raise ROMError(
                    "SPI_FLASH_MD5 trả 32 byte không phải ASCII: "
                    f"{payload.hex()}"
                ) from exc

            if not re.fullmatch(r"[0-9a-f]{32}", digest):
                raise ROMError(
                    f"SPI_FLASH_MD5 trả MD5 ASCII không hợp lệ: {payload!r}"
                )
            return digest

        if len(payload) == 16:
            return payload.hex()

        # ESP32 ROM trả MD5 ASCII 32 byte kèm phần status/reserved phía sau.
        # Thực tế ROM có thể trả 36 byte: 32 byte MD5 ASCII + 4 byte status/reserved.
        # Không được coi 4 byte cuối là một phần của MD5.
        # ESP32 ROM: MD5 ASCII 32 byte. Một số ROM trả thêm
        # reserved/status bytes phía sau (ví dụ 36 byte tổng cộng).
        # Chỉ 32 byte đầu mới là digest; trailing data không làm
        # response sai định dạng.
        if len(payload) >= 32:
            candidate = payload[:32]
            try:
                digest = candidate.decode("ascii").lower()
            except UnicodeDecodeError as exc:
                raise ROMError(
                    "SPI_FLASH_MD5: 32 byte đầu không phải ASCII MD5: "
                    f"{candidate.hex(' ')}"
                ) from exc

            if re.fullmatch(r"[0-9a-f]{32}", digest):
                trailing = payload[32:]
                if trailing and any(trailing):
                    self._log(
                        "[CẢNH BÁO] SPI_FLASH_MD5 có trailing data: "
                        + trailing.hex(" ")
                    )
                return digest

        if len(payload) in (18, 20):
            # Stub có thể trả 16 byte raw MD5 + status/reserved.
            return payload[:16].hex()

        raise ROMError(
            "SPI_FLASH_MD5 trả payload không đúng định dạng: "
            f"{len(payload)} byte | {payload[:64].hex(' ')}"
        )

    # Tương thích tên gọi cũ/mới.
    # Một số worker có thể gọi spi_flash_md5 thay vì flash_md5.
    spi_flash_md5 = flash_md5

    # ========================================================
    # CHANGE BAUD
    # ========================================================

    def change_baud(
        self,
        new_baud,
    ):

        self.command(
            CHANGE_BAUD,
            struct.pack(
                "<II",
                new_baud,
                self.baud,
            ),
            0,
            3.0,
            retries=0,
        )

        time.sleep(0.1)

        self.uart.set_baudrate(
            new_baud
        )

        self.baud = new_baud

    # ========================================================
    # READ FLASH SLOW
    # ========================================================

    def read_flash_slow(
        self,
        offset,
        length,
        progress=None,
    ):

        output = bytearray()

        while len(output) < length:

            n = min(
                64,
                length - len(output),
            )

            _, payload = self.check(
                READ_FLASH_SLOW,
                struct.pack(
                    "<II",
                    offset + len(output),
                    n,
                ),
                0,
                5.0,
                n,
                retries=1,
            )

            output.extend(payload)

            if progress:
                progress(
                    len(output),
                    length,
                )

        return bytes(output)

    # ========================================================
    # ERASE BY FLASH_BEGIN
    # ========================================================

    def erase_by_flash_begin(
        self,
        offset,
        size,
        progress=None,
    ):

        blocks = self.flash_begin(
            size,
            offset,
        )

        empty_block = (
            b"\xFF" *
            FLASH_WRITE_SIZE
        )

        total = blocks * FLASH_WRITE_SIZE

        for seq in range(blocks):

            self.flash_data(
                empty_block,
                seq,
            )

            if progress:

                progress(
                    min(
                        (seq + 1) *
                        FLASH_WRITE_SIZE,
                        total,
                    ),
                    total,
                )

        self.flash_end(
            reboot=False
        )

    # ========================================================
    # CHIP ERASE
    # ========================================================

    def chip_erase(
        self,
        size,
        offset=0,
    ):
        """
        Xóa vùng Flash bằng FLASH_BEGIN của ESP32 ROM.

        ESP32 ROM không hỗ trợ ERASE_FLASH (0xD0)
        như Stub Loader. FLASH_BEGIN (0x02) với
        erase_size bao phủ toàn bộ Flash sẽ yêu cầu
        ROM thực hiện erase trước khi ghi.
        """

        if size <= 0:
            raise ROMError(
                f"Kích thước Flash không hợp lệ: {size}"
            )

        if offset < 0:
            raise ROMError(
                f"Offset Flash không hợp lệ: {offset}"
            )

        erase_size = (
            (size + FLASH_SECTOR - 1)
            // FLASH_SECTOR
        ) * FLASH_SECTOR

        blocks = (
            erase_size + FLASH_WRITE_SIZE - 1
        ) // FLASH_WRITE_SIZE

        params = struct.pack(
            "<IIII",
            erase_size,
            blocks,
            FLASH_WRITE_SIZE,
            offset,
        )

        timeout = max(
            20.0,
            60.0 * erase_size / 1_000_000,
        )

        self._log(
            "FLASH ERASE BEGIN: "
            f"offset=0x{offset:X} "
            f"size={size} "
            f"erase_size={erase_size} "
            f"blocks={blocks} "
            f"timeout={timeout:.1f}s"
        )

        self.check(
            FLASH_BEGIN,
            params,
            0,
            timeout,
            0,
            retries=0,
        )

        self._log(
            "FLASH ERASE BEGIN ACK"
        )