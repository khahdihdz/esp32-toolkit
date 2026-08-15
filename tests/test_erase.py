import unittest
from unittest.mock import MagicMock, call
from esp32_rom import ESP32ROM, FLASH_WRITE_SIZE, ERASE_FLASH
from usbdevfs import USBTimeoutError, USBError

class T(unittest.TestCase):
    def test_erase_sends_flash_data_before_end(self):
        # SỬA LỖI: erase_by_flash_begin() từng gọi FLASH_END ngay sau
        # FLASH_BEGIN mà không gửi FLASH_DATA, khiến ROM ESP32 thật từ
        # chối FLASH_END (status 0x06). Test này khoá lại hành vi đúng:
        # phải gửi đủ số block FLASH_DATA khớp với những gì FLASH_BEGIN
        # đã khai báo, trước khi gọi FLASH_END, đúng thứ tự.
        rom = ESP32ROM.__new__(ESP32ROM)
        order = MagicMock()
        rom.flash_begin = MagicMock(side_effect=lambda *a: (order("begin"), 3)[1])
        rom.flash_data = MagicMock(side_effect=lambda *a: order("data"))
        rom.flash_end = MagicMock(side_effect=lambda *a, **k: order("end"))

        ESP32ROM.erase_by_flash_begin(rom, 0x1000, 3 * FLASH_WRITE_SIZE)

        rom.flash_begin.assert_called_once_with(3 * FLASH_WRITE_SIZE, 0x1000)
        self.assertEqual(rom.flash_data.call_count, 3)
        for i, c in enumerate(rom.flash_data.call_args_list):
            data, seq = c.args
            self.assertEqual(seq, i)
            self.assertEqual(data, b"\xFF" * FLASH_WRITE_SIZE)
        rom.flash_end.assert_called_once_with(reboot=False)
        self.assertEqual(
            [c.args[0] for c in order.call_args_list],
            ["begin", "data", "data", "data", "end"],
        )

    def test_chip_erase_sends_erase_flash_command_no_size_needed(self):
        # chip_erase() phải gửi đúng lệnh ROM ESP_ERASE_FLASH (0xD0) mà
        # không cần offset/size do người dùng cung cấp — chip tự xóa toàn
        # bộ bên trong. Đây là điều cho phép menu bỏ hẳn bước nhập tay
        # dung lượng Flash.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.check = MagicMock(return_value=(0, b""))

        ESP32ROM.chip_erase(rom)

        rom.check.assert_called_once()
        args = rom.check.call_args.args
        self.assertEqual(args[0], ERASE_FLASH)
        self.assertEqual(args[1], b"")

    def test_read_frame_tolerates_poll_timeouts_within_deadline(self):
        # SỬA LỖI: mỗi lần bulk_read(...,250) hết 250ms mà chưa có dữ liệu
        # sẽ raise USBTimeoutError (ETIMEDOUT/EAGAIN) — đây là chuyện bình
        # thường khi đang poll, KHÔNG phải lỗi USB thật. _read_frame() phải
        # bắt riêng lỗi này và tiếp tục poll tới hết deadline tổng của lệnh,
        # thay vì để nó văng thẳng ra ngoài như một lỗi treo máy/mất kết nối.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        from slip import SlipDecoder, slip_encode
        rom.decoder = SlipDecoder()
        import struct
        frame = slip_encode(struct.pack("<BBHI", 1, 0x08, 0, 0))
        rom.uart = MagicMock()
        # 2 lần poll đầu tiên "chưa có dữ liệu", lần thứ 3 mới có phản hồi.
        rom.uart.bulk_read.side_effect = [
            USBTimeoutError("ETIMEDOUT: quá thời gian (errno=110)"),
            USBTimeoutError("ETIMEDOUT: quá thời gian (errno=110)"),
            frame,
        ]

        got = ESP32ROM._read_frame(rom, timeout=3.0)

        self.assertEqual(got, struct.pack("<BBHI", 1, 0x08, 0, 0))
        self.assertEqual(rom.uart.bulk_read.call_count, 3)

    def test_read_frame_reraises_real_usb_errors(self):
        # Lỗi USB thật (EPIPE/ENODEV/EIO...) vẫn phải văng ra ngay, không
        # được nuốt như USBTimeoutError.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        from slip import SlipDecoder
        rom.decoder = SlipDecoder()
        rom.uart = MagicMock()
        rom.uart.bulk_read.side_effect = USBError("ENODEV: thiết bị đã ngắt kết nối")

        with self.assertRaises(USBError):
            ESP32ROM._read_frame(rom, timeout=3.0)

    def test_read_frame_keeps_extra_frames_from_same_chunk(self):
        # SỬA LỖI: nếu 1 lần bulk_read trả về NHIỀU hơn 1 SLIP frame hoàn
        # chỉnh cùng lúc (ACK đến trễ rồi ACK kế tiếp đến ngay sau, gộp
        # chung 1 lần poll 250ms), bản cũ chỉ lấy frames[0] và ÂM THẦM VỨT
        # các frame còn lại — làm mất phản hồi thật của lệnh sau, gây lệch
        # sổ sách block và cuối cùng ROM báo lỗi status 0x06 ở FLASH_END.
        # Test này khoá lại: 2 lệnh gọi _read_frame liên tiếp phải trả về
        # đúng 2 frame khác nhau dù cả hai đến trong cùng 1 chunk USB.
        rom = ESP32ROM.__new__(ESP32ROM)
        rom.debug = False
        from slip import SlipDecoder, slip_encode
        rom.decoder = SlipDecoder()
        import struct
        frame_a = struct.pack("<BBHI", 1, 0x03, 0, 0) + b"AAAA"
        frame_b = struct.pack("<BBHI", 1, 0x03, 0, 0) + b"BBBB"
        chunk = slip_encode(frame_a) + slip_encode(frame_b)
        rom.uart = MagicMock()
        rom.uart.bulk_read.side_effect = [chunk]

        first = ESP32ROM._read_frame(rom, timeout=3.0)
        second = ESP32ROM._read_frame(rom, timeout=3.0)

        self.assertEqual(first, frame_a)
        self.assertEqual(second, frame_b)
        # Chunk thứ 2 chỉ nên tới từ hàng đợi nội bộ, KHÔNG gọi bulk_read
        # thêm lần nào nữa.
        self.assertEqual(rom.uart.bulk_read.call_count, 1)

if __name__ == "__main__":
    unittest.main()
