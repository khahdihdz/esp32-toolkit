#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESP32 Toolkit - USB Flasher v3: MENU chạy trực tiếp trong Termux."""

from __future__ import annotations
import argparse, os, sys, tempfile
from pathlib import Path
from utils import (
    list_usb_devices, run_usb_worker, print_result, valid_bin, sha256_file,
    detect_firmware_files,
)

ROOT=Path(__file__).resolve().parent

LOGO = """
       │   │   │   │   │   │   │   │   │   │
       ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
       █ ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄ █
       █ █       ESP32  •  TOOLKIT       █ █
       █ █       USB FLASHER  •  v3      █ █
       █ ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀ █
       ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
       │   │   │   │   │   │   │   │   │   │
"""

MENU_SECTIONS = (
    ("THIẾT BỊ & KIỂM TRA", (
        ("1", "Kiểm tra kết nối / vào Download Mode"),
        ("2", "Chọn thiết bị USB"),
        ("3", "Thông tin chip & Flash"),
        ("4", "Đọc Factory MAC"),
    )),
    ("NẠP FIRMWARE", (
        ("5", "Nạp một file .BIN"),
        ("6", "Nạp nhiều file .BIN"),
        ("7", "Tự nhận diện firmware & nạp"),
    )),
    ("FLASH", (
        ("8", "Xóa toàn bộ Flash"),
    )),
    ("TIỆN ÍCH", (
        ("9", "Serial Monitor"),
        ("10", "Nhật ký hoạt động"),
    )),
)

_MENU_WIDTH = 58


def _menu_row(text: str = "") -> str:
    inner = _MENU_WIDTH - 4
    return "║ " + text[:inner].ljust(inner) + " ║"


def _menu_rule(left: str, mid: str, right: str) -> str:
    return left + mid * (_MENU_WIDTH - 2) + right


def banner():
    print(LOGO.strip("\n"))
    print(_menu_rule("╔", "═", "╗"))
    print(_menu_row("MENU CHÍNH".center(_MENU_WIDTH - 4)))
    print(_menu_rule("╠", "═", "╣"))
    for title, items in MENU_SECTIONS:
        print(_menu_row(title))
        for key, label in items:
            print(_menu_row(f"  {key:>2}. {label}"))
        print(_menu_rule("╠", "═", "╣"))
    print(_menu_row("  0. Thoát"))
    print(_menu_rule("╚", "═", "╝"))

def choose_device():
    ds=list_usb_devices()
    if not ds:
        print("[LỖI] Không tìm thấy USB qua termux-usb.")
        return None
    print("\nThiết bị USB:")
    for i,d in enumerate(ds,1): print(f"  {i}. {d}")
    if len(ds)==1: return ds[0]
    try:
        n=int(input("Chọn thiết bị: "))
        return ds[n-1]
    except Exception:
        return None

def call(device,*args):
    print(f"\n[ĐANG LÀM] termux-usb → Python USB Worker")
    cp=run_usb_worker(device,*args)
    print_result(cp)
    return cp.returncode==0

def ask_file():
    p=input("Đường dẫn firmware .BIN: ").strip().strip('"')
    ok,msg=valid_bin(p)
    if not ok: print("[LỖI]",msg); return None
    return p

def multi_flash(device):
    print("Nhập từng cặp offset + file; để trống offset để kết thúc.")
    pairs=[]
    while True:
        off=input("Offset (ví dụ 0x1000): ").strip()
        if not off: break
        f=input("File .BIN: ").strip().strip('"')
        ok,msg=valid_bin(f)
        if not ok: print("[LỖI]",msg); continue
        pairs.append((off,f))
    for off,f in pairs:
        print(f"\n=== NẠP {f} @ {off} ===")
        if not call(device,"--op","flash","--file",f,"--offset",off):
            print("[LỖI] Dừng danh sách BIN.")
            return
    print("[THÀNH CÔNG] Đã xử lý toàn bộ danh sách BIN.")

def auto_detect_flash(device):
    d=input("Thư mục chứa firmware .BIN [.]: ").strip().strip('"') or "."
    try:
        found=detect_firmware_files(d)
    except Exception as e:
        print("[LỖI]",e); return
    if not found:
        print("[LỖI] Không nhận diện được file firmware nào trong thư mục này.")
        print("Đặt tên theo chuẩn: bootloader.bin, partitions.bin, boot_app0.bin, firmware.bin")
        print("(hoặc merged.bin / *.factory.bin cho firmware gộp một file @ 0x0).")
        return
    print("\nĐã nhận diện:")
    for off,path,label in found:
        print(f"  {off:>8}  {label:<45} {path}")
    c=input("\nNạp toàn bộ danh sách trên? (C/K): ").strip().upper()
    if c!="C":
        print("[LỖI] Đã hủy.")
        return
    for off,path,label in found:
        print(f"\n=== NẠP {label} → {path} @ {off} ===")
        if not call(device,"--op","flash","--file",path,"--offset",off):
            print("[LỖI] Dừng do lỗi flash; các file còn lại chưa được nạp.")
            return
    print("[THÀNH CÔNG] Đã nạp toàn bộ firmware nhận diện được.")


def run_serial_monitor(device, *args):
    """Mở Serial Monitor trực tiếp qua termux-usb -E, không qua ROM worker."""
    from utils import ensure_usb_permission, TERMUX_API, PYTHON
    ensure_usb_permission(device)
    script = ROOT / "serial_monitor.py"
    cmd = [TERMUX_API, "-E", "-e", f"{PYTHON} -u {script} {' '.join(args)}", device]
    print("\n[ĐANG LÀM] Mở Serial Monitor ESP32")
    print("[THÔNG TIN] Lệnh:", " ".join(cmd))
    print("[THÔNG TIN] Ctrl+C để dừng monitor.\n")
    import subprocess
    try:
        cp = subprocess.run(cmd, text=True)
        if cp.returncode == 0:
            print("[THÀNH CÔNG] Serial Monitor đã kết thúc.")
        else:
            print(f"[LỖI] Serial Monitor thoát với mã {cp.returncode}.")
    except KeyboardInterrupt:
        print("\n[MONITOR] Đã dừng.")


def erase_flash(device):
    # Xóa TOÀN BỘ chip bằng lệnh ROM chuẩn ESP_ERASE_FLASH (giống esptool
    # erase_flash) — chip tự xóa hết bên trong, KHÔNG cần biết trước dung
    # lượng flash thật, nên không còn bắt người dùng gõ tay bất kỳ số liệu
    # nào (không cần nhập dung lượng / offset / kích thước như bản cũ).
    print("\nXóa Flash — sẽ xóa TOÀN BỘ chip (mọi dữ liệu → 0xFF).")
    print("Thao tác này KHÔNG THỂ hoàn tác và có thể mất 30 giây đến vài phút.")
    if input("Xác nhận xóa TOÀN BỘ Flash? (C/K): ").strip().upper() != "C":
        print("[LỖI] Đã hủy.")
        return
    call(device, "--op", "erase-chip")

def show_logs():
    log_dir = ROOT / "logs"
    live_log = Path.home() / "espflash-live.log"
    logs = sorted(log_dir.glob("*.log"))

    print(f"\nThư mục log : {log_dir}")
    print(f"Live log    : {live_log}")

    if not logs:
        print("Chưa có file log trong logs/.")
        return

    print("\nCác file log gần nhất:")
    for path in logs[-20:]:
        print(f"  {path.name}  ({path.stat().st_size:,} byte)")


def menu():
    device=None
    while True:
        banner()
        print(f"\nUSB hiện tại: {device or 'chưa chọn'}")
        c=input("Lựa chọn của bạn: ").strip()
        if c=="0": return
        try:
            if c=="1":
                device=device or choose_device()
                if device: call(device,"--op","detect")
            elif c=="2":
                device=choose_device()
                print("[THÀNH CÔNG] Đã chọn:",device) if device else None
            elif c=="3":
                device=device or choose_device()
                if device: call(device,"--op","info")
            elif c=="4":
                device=device or choose_device()
                if device: call(device,"--op","read-mac")
            elif c=="5":
                device=device or choose_device()
                f=ask_file()
                if device and f:
                    off=input("Offset [0x10000]: ").strip() or "0x10000"
                    call(device,"--op","flash","--file",f,"--offset",off)
            elif c=="6":
                device=device or choose_device()
                if device: multi_flash(device)
            elif c=="7":
                device=device or choose_device()
                if device: auto_detect_flash(device)
            elif c=="8":
                device=device or choose_device()
                if device: erase_flash(device)
            elif c=="9":
                device=device or choose_device()
                if device:
                    baud=input("Baud [115200]: ").strip() or "115200"
                    try:
                        baud_i=int(baud, 0)
                    except ValueError:
                        print("[LỖI] Baud không hợp lệ.")
                        continue
                    r=input("Reset ESP32 để bắt boot log? (C/K): ").strip().upper()
                    monitor_args=["--baud", str(baud_i)]
                    if r=="C": monitor_args.append("--reset")
                    if "--debug" in sys.argv: monitor_args.append("--debug")
                    run_serial_monitor(device, *monitor_args)
            elif c=="10":
                show_logs()
            else:
                print("[LỖI] Lựa chọn không hợp lệ.")
        except KeyboardInterrupt:
            print("\nĐã hủy.")
        except Exception as e:
            print("[LỖI]",e)
        input("\nNhấn Enter để tiếp tục...")

def cli():
    p=argparse.ArgumentParser(description="ESP32 Toolkit - USB Flasher v3")
    p.add_argument("--menu",action="store_true")
    p.add_argument("--device")
    p.add_argument("--detect",action="store_true")
    p.add_argument("--info",action="store_true")
    p.add_argument("--read-mac",action="store_true",dest="read_mac")
    p.add_argument("--monitor",action="store_true")
    p.add_argument("--baud",type=int,default=115200)
    p.add_argument("--reset",action="store_true")
    p.add_argument("--flash")
    p.add_argument("--offset",default="0x10000")
    p.add_argument("--debug",action="store_true")
    a=p.parse_args()
    if a.menu or len(sys.argv)==1:
        menu(); return
    d=a.device or choose_device()
    if not d: raise SystemExit(1)
    if a.detect: call(d,"--op","detect")
    elif a.info: call(d,"--op","info")
    elif a.read_mac: call(d,"--op","read-mac")
    elif a.monitor:
        m=["--baud",str(a.baud)]
        if a.reset: m.append("--reset")
        run_serial_monitor(d,*m)
    elif a.flash: call(d,"--op","flash","--file",a.flash,"--offset",a.offset,"--debug") if a.debug else call(d,"--op","flash","--file",a.flash,"--offset",a.offset)
    else: p.print_help()

if __name__=="__main__":
    cli()
