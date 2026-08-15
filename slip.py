#!/usr/bin/env python3
# -*- coding: utf-8 -*-
END=0xC0
ESC=0xDB
ESC_END=0xDC
ESC_ESC=0xDD

def slip_encode(data: bytes) -> bytes:
    return b"\xC0" + data.replace(b"\xDB", b"\xDB\xDD").replace(b"\xC0", b"\xDB\xDC") + b"\xC0"

class SlipDecoder:
    def __init__(self):
        self.buf=bytearray()
        self.escaped=False
    def feed(self, data: bytes) -> list[bytes]:
        out=[]
        for b in data:
            if b == END:
                if self.buf:
                    out.append(bytes(self.buf))
                    self.buf.clear()
                self.escaped=False
            elif b == ESC:
                self.escaped=True
            elif self.escaped:
                if b == ESC_END: self.buf.append(END)
                elif b == ESC_ESC: self.buf.append(ESC)
                else: raise ValueError(f"SLIP escape không hợp lệ: 0x{b:02X}")
                self.escaped=False
            else:
                self.buf.append(b)
        return out

def slip_decode(frame: bytes) -> bytes:
    d=SlipDecoder()
    r=d.feed(frame)
    if not r: raise ValueError("Không có SLIP frame hoàn chỉnh")
    return r[0]
