# ESP32 Toolkit — USB Flasher v3 cho Termux

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-online-2ea44f?logo=github)](https://khahdihdz.github.io/esp32-toolkit/)

Công cụ nạp, xóa và kiểm tra ESP32 qua USB OTG trên Android/Termux. Viết thuần Python, giao tiếp trực tiếp với ESP32 ROM Bootloader qua CP210x và USBDEVFS — không cần root, không dùng `pyserial`/`pyusb`/`libusb`.

> Trang giới thiệu tính năng: <https://khahdihdz.github.io/esp32-toolkit/>

## Tính năng

- Nạp một hoặc nhiều file `.bin` theo offset.
- Tự nhận diện firmware theo tên file.
- Xóa toàn bộ Flash bằng `ERASE_FLASH`.
- Đọc thông tin chip, JEDEC ID, dung lượng Flash, Factory MAC.
- Serial Monitor qua CP210x.
- Tự vào Download Mode bằng DTR/RTS; kiểm tra MD5 sau khi nạp.

## Kiến trúc

```text
Menu Python (Termux)
  → termux-usb -e
  → espflash-usb-callback
  → usb_worker.py
  → USB FD → USBDEVFS → CP2102/CP2102N
  → Bulk OUT 0x01 / Bulk IN 0x81
  → ESP32 ROM Bootloader → SLIP
```

Menu chạy trực tiếp trong Termux để `input()` hoạt động; worker USB chỉ chạy trong callback của `termux-usb`.

## Yêu cầu

- Termux + Python 3.
- Termux:API và gói `termux-api`.
- Cáp USB OTG; board dùng CP2102/CP2102N.
- ESP32 classic / ESP32-WROOM-32.

## Cài đặt

```bash
pkg update
pkg install python
```

Đặt repo tại `/data/data/com.termux/files/home/esp32-toolkit`, sau đó:

```bash
cd ~/esp32-toolkit
chmod +x *.sh
./install.sh
./install_callback.sh
```

`install_callback.sh` cài `espflash-usb-callback` vào `$PREFIX/bin`. Kiểm tra thiết bị bằng `termux-usb -l`.

## Chạy menu

```bash
cd ~/esp32-toolkit
python esp32_usb_flasher.py --menu
# hoặc
./start.sh
```

| Mục | Chức năng |
|---|---|
| `1` | Kiểm tra kết nối / vào Download Mode |
| `2` | Chọn thiết bị USB |
| `3` | Xem thông tin chip & Flash |
| `4` | Đọc Factory MAC |
| `5` | Nạp một file `.bin` |
| `6` | Nạp nhiều file `.bin` |
| `7` | Tự nhận diện firmware & nạp |
| `8` | Xóa toàn bộ Flash |
| `9` | Serial Monitor |
| `10` | Xem nhật ký hoạt động |
| `0` | Thoát |

Các thao tác `readback`, `verify`, `hardware-test`, `sync-raw` chưa được worker hỗ trợ nên không hiển thị trong menu.

Chạy nhanh bằng CLI:

```bash
python esp32_usb_flasher.py --detect
python esp32_usb_flasher.py --info
python esp32_usb_flasher.py --read-mac
python esp32_usb_flasher.py --flash firmware.bin --offset 0x10000
python esp32_usb_flasher.py --monitor --baud 115200 --reset
```

## Quy trình nạp firmware

1. Cắm ESP32 qua USB OTG.
2. Chọn `2` nếu có nhiều thiết bị USB.
3. Chọn `1` để kiểm tra kết nối / đưa ESP32 vào Download Mode.
4. Chọn `3` để xem chip và dung lượng Flash.
5. Chọn `5`, `6` hoặc `7` để nạp; chọn `9` để xem Serial Monitor.

## Tự nhận diện firmware (mục 7)

Menu `7` quét thư mục hiện tại (hoặc thư mục bạn nhập) và khớp tên file với offset chuẩn:

| Tên file (không phân biệt hoa/thường) | Offset | Ý nghĩa |
|---|---|---|
| `bootloader*.bin` | `0x1000` | Bootloader |
| `partitions.bin`, `partition-table.bin`, `partition_table.bin` | `0x8000` | Bảng phân vùng |
| `boot_app0*.bin`, `ota_data_initial*.bin` | `0xE000` | OTA data init |
| `firmware.bin`, `app.bin`, `*.ino.bin` | `0x10000` | Firmware (app) |
| `littlefs.bin` | `0x290000` | LittleFS / Web Dashboard |
| `merged*.bin`, `*.factory.bin` | `0x0` | Firmware gộp |

- Quét thư mục con tối đa 3 cấp (`build/`, `build/bootloader/`, `build/partition_table/`).
- File trùng offset: giữ file ở cấp thư mục nông hơn, bỏ qua file còn lại kèm cảnh báo.
- Có `merged*.bin` hoặc `*.factory.bin` thì chỉ nạp file gộp, bỏ qua các file khác.
- Menu luôn in danh sách để xác nhận trước khi nạp.

Nếu tên file không theo chuẩn, dùng mục `5` hoặc `6` để nhập offset thủ công.

## Xóa Flash (mục 8)

Mục `8` xóa **toàn bộ chip** bằng `ERASE_FLASH` của ROM (giống `erase_flash` của esptool):

- Không cần nhập dung lượng, offset hay kích thước.
- Cần xác nhận `C/K` trước khi xóa.
- Dữ liệu trên Flash chuyển thành `0xFF`; không thể hoàn tác.
- Thời gian xóa: khoảng 30 giây đến vài phút tùy dung lượng chip.

Các preset xóa vùng có trong `utils.py` nhưng chưa được nối vào menu v3.

## Giao thức & kỹ thuật

- Packet ROM: `direction(1) command(1) length(2) checksum(4) payload`, bọc SLIP `C0 ... C0`.
- Command chính: `SYNC 0x08`, `READ_REG 0x0A`, `SPI_ATTACH 0x0D`, `SPI_SET_PARAMS 0x0B`, `READ_FLASH_SLOW 0x0E`, `CHANGE_BAUD 0x0F`, `FLASH_BEGIN 0x02`, `FLASH_DATA 0x03`, `FLASH_END 0x04`, `SPI_FLASH_MD5 0x13`, `ERASE_FLASH 0xD0`.
- Checksum XOR bắt đầu từ `0xEF`; block flash `0x400` byte; sector `0x1000` byte.
- Không hard-code 4 MB: worker đọc JEDEC sau `SPI_ATTACH` rồi truyền dung lượng thực cho `SET_FLASH_PARAMS`.
- Sau khi nạp, `esp32_flash.py` đọc lại MD5 bằng `SPI_FLASH_MD5`; chỉ báo thành công khi MD5 khớp.
- `READ_FLASH_SLOW` giới hạn 64 byte/lệnh; menu chưa nối readback.

## Khắc phục lỗi

### ESP32 không vào Download Mode

1. Giữ BOOT.
2. Nhấn EN/RESET.
3. Giữ BOOT 1–2 giây.
4. Thả BOOT.
5. Chạy lại mục `1`.

Nếu board dùng mạch auto-reset đảo cực khác chuẩn, giữ BOOT thủ công rồi chạy mục `1`.

### `termux-usb: too many arguments`

Không truyền `--op`, `--file`... trực tiếp sau đường dẫn thiết bị. Dùng menu hoặc CLI của công cụ. Kiểm tra callback:

```bash
ls -l "$PREFIX/bin/espflash-usb-callback"
# nếu chưa có:
./install_callback.sh
```

### ROM báo `command 0x04: 01060000` khi xóa Flash

Nguyên nhân cũ: gửi `FLASH_END` trước khi gửi đủ số gói `FLASH_DATA` mà `FLASH_BEGIN` đã khai báo. Đã sửa bằng cách gửi đủ block `FLASH_DATA` toàn byte `0xFF` rồi mới gọi `FLASH_END`; `tests/test_erase.py` khoá lại thứ tự này.

### Serial Monitor không có dữ liệu

- Kiểm tra đúng baud (mặc định `115200`).
- Chọn reset `C` để bắt boot log.
- Serial Monitor không đưa ESP32 vào Download Mode và không flash/erase.
- Kiểm tra dây TX/RX và driver CP210x.

## Giới hạn hiện tại

- Tập trung vào **ESP32 classic / ESP32-WROOM-32**; ESP32-S2/S3/C3/C6 có thể khác protocol.
- `readback`, `verify`, `hardware-test`, `sync-raw` chưa được nối vào worker/menu.
- Menu chưa đổi baud; Serial Monitor nhận `--baud` riêng.
- Không hard-code 4 MB; dung lượng Flash lấy từ JEDEC.

## Kiểm thử & lịch sử

```bash
python -m unittest discover -s tests -v
```

- **v3.1** — chẩn đoán SYNC, sửa thứ tự DTR/RTS theo Espressif, thêm `sync-raw`.
- **V3 Fixed 4/6** — ổn định callback Termux và request của worker.
- **Bản hiện tại** — thêm logo ESP32, menu gọn 1–10, ẩn mục chưa hỗ trợ, đồng bộ README.

Chi tiết xem `git log`.

## Nguồn protocol

Cấu trúc command, checksum, block `0x400`, `FLASH_BEGIN/DATA/END`, `SPI_ATTACH`, `SPI_FLASH_MD5` và `READ_FLASH_SLOW` được đối chiếu với mã nguồn esptool của Espressif. v3 không import esptool và không dùng pyserial.

## Giấy phép

Dự án được phát hành theo **GNU General Public License v3.0**. Xem [LICENSE](LICENSE) để biết toàn văn.

Bạn có thể dùng, sửa và phân phối lại theo các điều khoản GPLv3; nếu phân phối bản sửa đổi, phải công bố mã nguồn theo cùng giấy phép.

Copyright (C) 2026 khahdihdz.
