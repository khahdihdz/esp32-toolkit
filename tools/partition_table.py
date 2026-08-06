#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
partition_table.py
===================
Doc va phan tich file partitions.bin (dinh dang bang phan vung nhi phan
cua ESP-IDF/Arduino-esp32) de tu dong tim DUNG offset cua vung du lieu
LittleFS/SPIFFS, thay vi doan mot gia tri co dinh.

Ly do can co file nay: cac partition scheme khac nhau (default.csv,
min_spiffs.csv, default_8MB.csv, ...) dat vung spiffs o NHUNG OFFSET
KHAC NHAU. Vi du min_spiffs.csv (dung cho project co OTA, app lon)
dat spiffs o 0x3D0000, trong khi default.csv dat o 0x290000. Doan
sai offset se khien flash.sh ghi littlefs.bin vao NHAM vung (thuong la
de vao giua slot OTA du phong "app1"), va verify.sh so sanh MD5 sai
vung dan den bao loi gia du flash dung.

Dinh dang 1 entry (32 byte, little-endian):
    2 byte  magic (0xAA 0x50)
    1 byte  type      (0x00 = app, 0x01 = data)
    1 byte  subtype   (0x82 = spiffs/littlefs khi type=data)
    4 byte  offset
    4 byte  size
    16 byte name (chuoi ket thuc bang NUL, phan con lai la NUL)
    4 byte  flags
Bang ket thuc khi gap 2 byte 0xFFFF (vung trong, chua ghi).
"""

from __future__ import annotations

import struct
from typing import List, Optional, TypedDict

PARTITION_MAGIC = b"\xaa\x50"
TYPE_APP = 0x00
TYPE_DATA = 0x01
SUBTYPE_SPIFFS = 0x82  # dung chung cho ca SPIFFS va LittleFS trong bang phan vung


class PartitionEntry(TypedDict):
    name: str
    type: int
    subtype: int
    offset: int
    size: int


def parse_partition_table(path: str) -> List[PartitionEntry]:
    """Doc file partitions.bin, tra ve danh sach cac partition tim thay."""
    with open(path, "rb") as f:
        data = f.read()

    entries: List[PartitionEntry] = []
    i = 0
    while i + 32 <= len(data):
        magic = data[i : i + 2]
        if magic != PARTITION_MAGIC:
            break  # het bang (gap 0xFFFF hoac du lieu la)
        typ, subtype = data[i + 2], data[i + 3]
        offset, size = struct.unpack("<II", data[i + 4 : i + 12])
        name_raw = data[i + 12 : i + 28]
        name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        entries.append(
            {"name": name, "type": typ, "subtype": subtype, "offset": offset, "size": size}
        )
        i += 32
    return entries


def find_littlefs_offset(path: str) -> Optional[int]:
    """
    Tim offset cua vung du lieu LittleFS/SPIFFS trong bang phan vung.
    Uu tien khop theo subtype (0x82), fallback theo ten thuong gap
    ("spiffs", "littlefs") neu subtype khong khop (mot so board custom).
    Tra ve None neu khong tim thay.
    """
    entries = parse_partition_table(path)

    for e in entries:
        if e["type"] == TYPE_DATA and e["subtype"] == SUBTYPE_SPIFFS:
            return e["offset"]

    for e in entries:
        name_lower = e["name"].lower()
        if e["type"] == TYPE_DATA and ("spiffs" in name_lower or "littlefs" in name_lower):
            return e["offset"]

    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 3):
        print("Cach dung: python3 partition_table.py <duong_dan_partitions.bin> [--littlefs-offset-only]")
        sys.exit(1)

    path = sys.argv[1]
    quiet_mode = len(sys.argv) == 3 and sys.argv[2] == "--littlefs-offset-only"

    if quiet_mode:
        # Chi in DUY NHAT gia tri offset dang hex (vd: "0x3d0000") ra
        # stdout, khong gi khac - de script bash doc truc tiep bang
        # command substitution ma khong can grep -P (khong co san tren
        # moi ban Termux/busybox).
        offset = find_littlefs_offset(path)
        if offset is None:
            sys.exit(2)
        print(f"{offset:#x}")
        sys.exit(0)

    entries = parse_partition_table(path)
    for e in entries:
        print(
            f"{e['name']:<12s} type={e['type']:#04x} subtype={e['subtype']:#04x} "
            f"offset={e['offset']:#x} size={e['size']:#x}"
        )

    offset = find_littlefs_offset(path)
    if offset is not None:
        print(f"\n-> LittleFS/SPIFFS offset: {offset:#x}")
    else:
        print("\n-> Khong tim thay vung LittleFS/SPIFFS trong bang phan vung.")
        sys.exit(2)
