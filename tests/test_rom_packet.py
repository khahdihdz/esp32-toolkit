import unittest, struct
class T(unittest.TestCase):
    def test_header(self):
        p=struct.pack("<BBHI",0,0x08,36,0xEF)
        self.assertEqual(len(p),8)
if __name__=="__main__": unittest.main()
