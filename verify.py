#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import hashlib
from pathlib import Path

def hashes(data: bytes) -> tuple[str,str]:
    return hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest()

def file_hashes(path: str | Path) -> tuple[str,str]:
    md5=hashlib.md5(); sha=hashlib.sha256()
    with open(path,"rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            md5.update(b); sha.update(b)
    return md5.hexdigest(), sha.hexdigest()

def compare_file_data(path: str | Path, data: bytes) -> bool:
    with open(path,"rb") as f:
        return f.read()==data
