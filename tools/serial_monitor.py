#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_monitor.py
==================
Serial Monitor thuần Python cho ESP32 trên Android/Termux, không dùng
PlatformIO, không dùng pySerial. Đọc dữ liệu UART qua UartBridge (bulk
transfer USB) và hiển thị theo thời gian thực, tự động reconnect nếu
mất kết nối.

Được monitor.sh gọi bên trong MỘT phiên `termux-usb -r -e` duy nhất,
với đường dẫn thiết bị được termux-usb tự thêm vào cuối dòng lệnh:

    python3 serial_monitor.py --baud 115200 --log session.log /dev/bus/usb/001/002
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger  # noqa: E402
import config as toolkit_config  # noqa: E402
from logger import Colors  # noqa: E402
from android_usb import AndroidUsbDevice, AndroidUsbError  # noqa: E402
from usb_bridge import create_bridge, UartBridgeError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial Monitor cho ESP32 tren Android/Termux")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mac dinh 115200)")
    parser.add_argument("--log", default=None, help="Duong dan file de luu log")
    parser.add_argument("--filter", default=None, help="Regex de loc dong hien thi")
    parser.add_argument("--no-timestamp", action="store_true", help="Tat timestamp")
    parser.add_argument("--no-color", action="store_true", help="Tat mau ANSI")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Khong tu dong reset qua DTR/RTS - dung khi board khong co mach auto-reset "
        "hoac dau day DTR/RTS khac chuan (tu bam nut RESET/EN vat ly thay the)",
    )
    parser.add_argument("device", help="Duong dan thiet bi USB (do termux-usb tu them vao)")
    return parser


_PRINTABLE_MIN = 0x20  # space
_PRINTABLE_MAX = 0x7E  # ~


def sanitize_for_display(raw: bytes) -> tuple[str, float]:
    """Chuyen bytes tho thanh chuoi AN TOAN de in ra terminal.

    Moi byte dieu khien (ESC, backspace, control chars...) deu bi thay
    the bang placeholder hien thi duoc, KHONG bao gio in thang byte
    dieu khien ra terminal - vi cac byte nay (vd 0x1B ESC) co the chua
    ANSI escape sequence lam xoa/di chuyen con tro, khien du lieu that
    su da duoc print() nhung nguoi dung khong he thay gi tren man hinh.

    Tra ve (chuoi_an_toan, ty_le_byte_khong_in_duoc).
    """
    if not raw:
        return "", 0.0
    out_chars = []
    bad = 0
    for b in raw:
        if b in (0x09,):  # cho phep tab
            out_chars.append(chr(b))
        elif _PRINTABLE_MIN <= b <= _PRINTABLE_MAX or b >= 0xA0:
            out_chars.append(chr(b))
        else:
            out_chars.append(f"\\x{b:02x}")
            bad += 1
    ratio = bad / len(raw)
    return "".join(out_chars), ratio


def colorize_line(line: str) -> str:
    """Tô màu đơn giản theo mức log phổ biến của ESP-IDF (E/W/I/D)."""
    if re.match(r"^\s*E \(", line) or " error" in line.lower():
        return f"{Colors.RED}{line}{Colors.RESET}"
    if re.match(r"^\s*W \(", line) or "warn" in line.lower():
        return f"{Colors.YELLOW}{line}{Colors.RESET}"
    if re.match(r"^\s*I \(", line):
        return f"{Colors.GREEN}{line}{Colors.RESET}"
    return line


def main() -> int:
    # QUAN TRONG: khi stdout bi pipe (khong phai tty that, vd qua
    # termux-usb), Python tu chuyen sang block-buffering (~8KB) thay vi
    # line-buffering. Ket qua: du lieu serial da print() nhung bi "giam"
    # trong buffer, khong bao gio hien ra man hinh cho toi khi buffer day
    # hoac chuong trinh thoat. Ep line-buffering (hoac unbuffered neu
    # reconfigure khong ho tro) ngay tu dau de moi dong hien ra tuc thi.
    try:
        sys.stdout.reconfigure(line_buffering=True, write_through=True)
    except (AttributeError, ValueError):
        sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)

    args = build_parser().parse_args()
    cfg = toolkit_config.load_config()

    filter_re = re.compile(args.filter) if args.filter else None
    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    logger.header("ESP32 SERIAL MONITOR")
    logger.info(f"Thiet bi : {args.device}")
    logger.info(f"Baudrate : {args.baud}")
    if args.log:
        logger.info(f"Luu log  : {args.log}")
    logger.info("Nhan Ctrl+C de thoat.\n")

    reconnect_delay = float(cfg.get("reconnect_initial_delay_sec", 1))
    reconnect_max = float(cfg.get("reconnect_max_delay_sec", 10))
    line_buf = bytearray()

    while True:
        usb_dev = AndroidUsbDevice(args.device)
        try:
            usb_dev.open()
            vendor_id, product_id = usb_dev.get_device_descriptor()
            bridge = create_bridge(usb_dev, vendor_id, product_id)
            logger.info(f"USB: VID={vendor_id:#06x} PID={product_id:#06x} -> driver phat hien: {bridge.NAME}")
            bridge.open()
            logger.info(
                f"Da mo UART qua {bridge.NAME}: endpoint IN=0x{bridge.ep_in:02x} "
                f"OUT=0x{bridge.ep_out:02x} tren interface {bridge.interface}"
            )
            bridge.set_baud(args.baud)
            reconnect_delay = float(cfg.get("reconnect_initial_delay_sec", 1))

            # Reset ESP32 khi vua ket noi, giong hanh vi cua Arduino IDE /
            # PlatformIO monitor: neu khong reset, cac dong log chi in MOT
            # LAN trong setup() (vd: log WiFi AP mode) da troi qua tu luc
            # flash xong se KHONG BAO GIO xuat hien, vi loop() co the khong
            # in gi them. Reset o day dam bao luon thay lai tu dau.
            try:
                if args.no_reset:
                    logger.info("Bo qua auto-reset (--no-reset).")
                    logger.warning(
                        "Neu khong thay log, hay BAM NUT RESET/EN vat ly tren mach NGAY BAY GIO.\n"
                    )
                else:
                    bridge.hard_reset()
                    logger.info("Da reset ESP32, cho khoi dong lai...")
                    logger.warning(
                        "Neu sau vai giay van khong thay log gi, mach co the khong co "
                        "mach auto-reset qua DTR/RTS - hay BAM NUT RESET/EN vat ly, "
                        "hoac chay lai voi bien NO_RESET=1.\n"
                    )
            except Exception as exc:  # không nghiêm trọng, vẫn tiếp tục lắng nghe
                logger.warning(f"Khong the reset ESP32 tu dong: {exc}")

            logger.ok("Da ket noi UART. Dang lang nghe du lieu...\n")

            total_bytes = 0
            last_data_ts = time.time()
            last_idle_warn_ts = 0.0

            while True:
                chunk = bridge.read_available(max_size=2048, timeout_ms=200)
                if not chunk:
                    # Khong nhan duoc byte nao trong 200ms nay. Neu da lau
                    # khong co gi (ke ca sau khi bam RESET vat ly), canh bao
                    # dinh ky de phan biet "khong co byte nao toi USB" voi
                    # "co byte nhung khong phai text co \\n" (vd sai baud).
                    now = time.time()
                    if now - last_data_ts > 3 and now - last_idle_warn_ts > 3:
                        logger.warning(
                            f"[DEBUG] Chua nhan duoc byte nao qua USB trong "
                            f"{now - last_data_ts:.0f}s (tong tu dau: {total_bytes} byte). "
                            "Neu con so nay mai la 0 ke ca sau khi bam RESET vat ly, "
                            "van de nam o kenh USB/endpoint, khong phai o firmware/baud."
                        )
                        last_idle_warn_ts = now
                    continue

                total_bytes += len(chunk)
                last_data_ts = time.time()
                line_buf.extend(chunk)

                # Neu buffer phinh to ma khong co byte xuong dong nao, rat
                # co the dang nhan du lieu SAI BAUD (rac nhi phan). Dump hex
                # de nguoi dung tu mat thay co du lieu that dang toi.
                if len(line_buf) > 512 and b"\n" not in line_buf:
                    preview = bytes(line_buf[:64])
                    logger.warning(
                        f"[DEBUG] Da nhan {len(line_buf)} byte lien tuc khong co ky tu "
                        f"xuong dong nao -> nghi ngo SAI BAUDRATE. 64 byte dau (hex): "
                        f"{preview.hex(' ')}"
                    )
                    logger.warning(
                        "[DEBUG] Neu day la ky tu co nghia bi bam nham baud, hay thu: "
                        "BAUD=74880 ./monitor.sh (log mo dau ROM) hoac doi lai baud "
                        "khop voi Serial.begin()/ESP_LOGx trong firmware.\n"
                    )
                    line_buf = bytearray()

                while b"\n" in line_buf:
                    raw_line, _, rest = line_buf.partition(b"\n")
                    line_buf = bytearray(rest)

                    # QUAN TRONG: khong bao gio print() thang byte tho ra
                    # terminal. Neu day la rac do sai baud, no rat de chua
                    # byte dieu khien (ESC, backspace...) co the AM THAM
                    # xoa/di chuyen con tro sau khi in - lam nguoi dung
                    # tuong nhu khong co gi duoc in ra, du print() da chay.
                    safe_text, bad_ratio = sanitize_for_display(bytes(raw_line).rstrip(b"\r"))

                    if filter_re and not filter_re.search(safe_text):
                        continue

                    ts = ""
                    if not args.no_timestamp:
                        ts = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] "

                    if bad_ratio > 0.15:
                        # Dong nay co ve la rac nhi phan (sai baud), du co
                        # byte 0x0A "tinh co". Bao ro rang thay vi im lang.
                        logger.warning(
                            f"{ts}[DEBUG] Dong co {bad_ratio*100:.0f}% byte khong in duoc "
                            f"-> nghi ngo SAI BAUDRATE: {safe_text[:120]}"
                        )
                    else:
                        display_line = ts + (colorize_line(safe_text) if not args.no_color else safe_text)
                        # flush=True: lop bao hiem thu hai, phong truong hop
                        # reconfigure() o tren khong co hieu luc tren mot so
                        # ban Termux/Python build cu.
                        # QUAN TRONG: in ra stderr, KHONG PHAI stdout. Da xac
                        # dinh duoc bang debug thuc te: khi chay qua
                        # `termux-usb -r -e`, stdout cua tien trinh con bi
                        # "nuot mat" (khong hien ra man hinh Termux) trong
                        # khi stderr van hien binh thuong - moi dong
                        # logger.info/ok/warning (deu dung stderr) hien du,
                        # nhung print() thuong (stdout) thi khong bao gio
                        # thay, du bo dem total_bytes van tang dung. In ra
                        # stderr o day de dam bao du lieu serial thuc su
                        # hien tren man hinh thay vi bien mat am tham.
                        print(display_line, file=sys.stderr, flush=True)

                    if log_file:
                        log_file.write(f"{ts}{safe_text}\n")
                        log_file.flush()

        except KeyboardInterrupt:
            logger.warning("\nDa dung Serial Monitor.")
            return 0
        except (AndroidUsbError, UartBridgeError) as exc:
            logger.error(f"Mat ket noi UART: {exc}")
            logger.info(f"Thu ket noi lai sau {reconnect_delay:.0f} giay...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, reconnect_max)
        finally:
            usb_dev.close()
            if log_file:
                log_file.flush()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
