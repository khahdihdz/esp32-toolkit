import unittest
from esp32_rom import checksum
class T(unittest.TestCase):
    def test_sync_payload_checksum_is_not_forced_to_ef(self):
        # SYNC của esptool truyền checksum field = 0; 0xEF là giá trị khởi tạo
        # của hàm checksum cho FLASH_DATA, không phải checksum cố định của SYNC.
        self.assertEqual(checksum(b"\x07\x07\x12\x20"+b"\x55"*32),0xDD)
if __name__=="__main__": unittest.main()
