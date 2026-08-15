import unittest, os
class T(unittest.TestCase):
    def test_no_pyserial(self):
        root=os.path.dirname(os.path.dirname(__file__))
        for name in os.listdir(root):
            if name.endswith(".py"):
                txt=open(os.path.join(root,name),encoding="utf-8").read()
                self.assertNotIn("import serial",txt)
                self.assertNotIn("import pyserial",txt)
if __name__=="__main__": unittest.main()
