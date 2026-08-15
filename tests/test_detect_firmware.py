import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import detect_firmware_files


class T(unittest.TestCase):
    def _touch(self, root: Path, rel: str, size: int = 16):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff" * size)
        return p

    def test_arduino_style_flat_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._touch(root, "bootloader.bin")
            self._touch(root, "partitions.bin")
            self._touch(root, "boot_app0.bin")
            self._touch(root, "firmware.bin")
            found = detect_firmware_files(root)
            offsets = [o for o, _, _ in found]
            self.assertEqual(offsets, ["0x1000", "0x8000", "0xE000", "0x10000"])

    def test_esp_idf_nested_build_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._touch(root, "build/bootloader/bootloader.bin")
            self._touch(root, "build/partition_table/partition-table.bin")
            self._touch(root, "build/myapp.ino.bin")
            found = detect_firmware_files(root)
            offmap = {o: l for o, p, l in found}
            self.assertIn("0x1000", offmap)
            self.assertIn("0x8000", offmap)
            self.assertIn("0x10000", offmap)

    def test_merged_image_takes_priority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._touch(root, "bootloader.bin")
            self._touch(root, "merged-firmware.bin")
            found = detect_firmware_files(root)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0][0], "0x0")

    def test_no_match_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._touch(root, "readme.bin")  # doesn't match any rule
            found = detect_firmware_files(root)
            self.assertEqual(found, [])

    def test_duplicate_offset_keeps_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._touch(root, "firmware.bin")
            self._touch(root, "sub/app.bin")  # also maps to 0x10000, shallower wins
            found = detect_firmware_files(root)
            offsets = [o for o, _, _ in found]
            self.assertEqual(offsets.count("0x10000"), 1)


if __name__ == "__main__":
    unittest.main()
