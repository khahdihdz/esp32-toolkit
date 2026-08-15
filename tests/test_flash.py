import unittest
from esp32_flash import pad4
class T(unittest.TestCase):
    def test_pad(self):
        self.assertEqual(pad4(b"abc"),b"abc\xff")
if __name__=="__main__": unittest.main()
