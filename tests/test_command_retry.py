import unittest, struct
from unittest.mock import MagicMock
from esp32_rom import ESP32ROM, ROMError, SYNC


class T(unittest.TestCase):
    def test_command_retries_once_on_true_timeout_then_succeeds(self):
        # SỬA LỖI: trước đây command() bỏ cuộc ngay khi _read_frame() hết
        # thời gian ở LẦN THỬ ĐẦU TIÊN, dù chỉ mất 1 gói thoáng qua (chuyện
        # bình thường với USB OTG qua termux-usb). Giờ command() phải gửi
        # lại gói một lần (retries=1 mặc định) trước khi thật sự báo lỗi.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        rom.uart = MagicMock()
        good = struct.pack("<BBHI", 1, SYNC, 0, 0)
        # Lần gửi đầu: _read_frame timeout thật (không có frame nào).
        # Lần gửi thứ hai (sau khi command() tự gửi lại): có phản hồi.
        rom._read_frame = MagicMock(side_effect=[
            ROMError("Timeout: không nhận được SLIP response từ ESP32."),
            good,
        ])

        val, payload = ESP32ROM.command(rom, SYNC, b"", 0, 0.7)

        self.assertEqual(payload, b"")
        self.assertEqual(rom.uart.bulk_write.call_count, 2)

    def test_command_reports_op_code_after_exhausting_retries(self):
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        rom.uart = MagicMock()
        rom._read_frame = MagicMock(
            side_effect=ROMError("Timeout: không nhận được SLIP response từ ESP32.")
        )

        with self.assertRaises(ROMError) as ctx:
            ESP32ROM.command(rom, SYNC, b"", 0, 0.7)

        self.assertIn(f"0x{SYNC:02X}", str(ctx.exception))
        # 1 lần gửi ban đầu + 1 lần thử lại mặc định (retries=1) = 2 lần.
        self.assertEqual(rom.uart.bulk_write.call_count, 2)

    def test_flash_end_never_auto_retries(self):
        # SỬA LỖI: FLASH_END không idempotent — nếu command() tự gửi lại
        # do ACK chỉ đến chậm (không phải mất gói thật), ROM có thể đã rời
        # trạng thái chờ FLASH_END và báo lỗi "Failed to act on received
        # message" (status 0x06) cho gói gửi lại thừa. flash_end() PHẢI
        # gọi command()/check() với retries=0.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        rom.uart = MagicMock()
        rom._read_frame = MagicMock(
            side_effect=ROMError("Timeout: không nhận được SLIP response từ ESP32.")
        )

        with self.assertRaises(ROMError):
            ESP32ROM.flash_end(rom, reboot=False)

        # Chỉ đúng 1 lần gửi — không có lần gửi lại nào.
        self.assertEqual(rom.uart.bulk_write.call_count, 1)

    def test_chip_erase_never_auto_retries(self):
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        rom.uart = MagicMock()
        rom._read_frame = MagicMock(
            side_effect=ROMError("Timeout: không nhận được SLIP response từ ESP32.")
        )

        with self.assertRaises(ROMError):
            ESP32ROM.chip_erase(rom, timeout=1.0)

        self.assertEqual(rom.uart.bulk_write.call_count, 1)

    def test_change_baud_never_auto_retries(self):
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        rom.baud = 115200
        rom.uart = MagicMock()
        rom._read_frame = MagicMock(
            side_effect=ROMError("Timeout: không nhận được SLIP response từ ESP32.")
        )

        with self.assertRaises(ROMError):
            ESP32ROM.change_baud(rom, 921600)

        self.assertEqual(rom.uart.bulk_write.call_count, 1)
        # Không được đổi baud host-side khi lệnh thất bại.
        rom.uart.set_baudrate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
