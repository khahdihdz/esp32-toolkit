import unittest
from utils import parse_int
class T(unittest.TestCase):
    def test_int(self):
        self.assertEqual(parse_int("0x1000"),4096)
if __name__=="__main__": unittest.main()
