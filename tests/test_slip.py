import unittest
from slip import slip_encode, slip_decode
class T(unittest.TestCase):
    def test_roundtrip(self):
        x=b"\x00\xc0\xdb\xff"
        self.assertEqual(slip_decode(slip_encode(x)),x)
if __name__=="__main__": unittest.main()
