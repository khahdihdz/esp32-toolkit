# ESP32 USB Flasher v3 — Termux Android

## Kiến trúc

```text
Menu Python chạy trực tiếp trong Termux
        ↓
termux-usb -E
        ↓
run_worker.sh
        ↓
usb_worker.py
        ↓
TERMUX_USB_FD
        ↓
USBDEVFS
        ↓
CP2102 / CP2102N
        ↓
Bulk OUT 0x01 / Bulk IN 0x81
        ↓
ESP32 ROM Bootloader
        ↓
SLIP
```

Menu **không** chạy dưới `termux-usb`, vì vậy `input()` hoạt động bình thường trên Termux. Worker USB mới chạy trong callback và lấy `TERMUX_USB_FD`.

## Không dùng

- pyserial
- pyusb
- libusb
- ADB
- MTP
- `/dev/ttyUSB*`
- `/dev/ttyACM*`
- root

## Cài đặt

```bash
pkg update
pkg install python
```

Cài Termux:API tương thích với Termux và bảo đảm lệnh `termux-usb` hoạt động.

Giải nén thư mục vào:

```text
/data/data/com.termux/files/home/esp32-toolkit
```

Sau đó:

```bash
cd ~/esp32-toolkit
chmod +x *.sh
./install.sh
```

## Tự nhận diện firmware & offset (mục 7)

Menu `7` quét một thư mục (mặc định thư mục hiện tại) và tự khớp tên file với offset chuẩn:

| Tên file khớp (không phân biệt hoa/thường) | Offset  | Ý nghĩa |
|---|---|---|
| `bootloader*.bin` | `0x1000` | Bootloader |
| `partitions.bin`, `partition-table.bin`, `partition_table.bin` | `0x8000` | Bảng phân vùng |
| `boot_app0*.bin`, `ota_data_initial*.bin` | `0xE000` | OTA data init |
| `firmware.bin`, `app.bin`, `*.ino.bin` | `0x10000` | Firmware (app) |
| `merged*.bin`, `*.factory.bin` | `0x0` | Firmware gộp — nếu có, **chỉ nạp file này**, bỏ qua các file trên |

Có quét cả thư mục con tối đa 3 cấp để bắt được cấu trúc `build/`, `build/bootloader/`, `build/partition_table/` của ESP-IDF. Nếu 2 file cùng khớp 1 offset, file ở cấp thư mục nông hơn (gần thư mục gốc hơn) được giữ, file còn lại bị bỏ qua kèm cảnh báo. Sau khi quét, menu in danh sách để xác nhận trước khi nạp — không tự nạp khi chưa xác nhận.

Nếu tên file không theo chuẩn trên, dùng mục `5` (một file) hoặc mục `6` (nhiều file, nhập tay từng cặp offset + file).

## Kiểm tra callback USB

```bash
termux-usb -l
```

Ví dụ thiết bị:

```text
/dev/bus/usb/001/002
```

Kiểm tra worker:

```bash
termux-usb -E -e ~/esp32-toolkit/run_worker.sh \
/dev/bus/usb/001/002 --op info
```

## Chạy menu

```bash
cd ~/esp32-toolkit
python esp32_usb_flasher.py --menu
```

Menu chính:

| Mục | Chức năng |
|---|---|
| `1` | Kiểm tra kết nối / đưa ESP32 vào Download Mode |
| `2` | Chọn thiết bị USB |
| `3` | Xem thông tin chip & Flash |
| `4` | Đọc Factory MAC |
| `5` | Nạp một file `.bin` |
| `6` | Nạp nhiều file `.bin` |
| `7` | Tự nhận diện firmware trong thư mục & nạp |
| `8` | Xóa toàn bộ Flash |
| `9` | Serial Monitor |
| `10` | Xem nhật ký hoạt động |
| `0` | Thoát |

Các thao tác đọc lại Flash, xác minh và test phần cứng chưa được worker v3 hỗ trợ nên không còn hiển thị trong menu.

## ESP32 ROM protocol

v3 dùng packet ROM dạng:

```text
direction(1) command(1) length(2) checksum(4) payload
```

và SLIP `C0 ... C0`.

Các command chính:

- `SYNC = 0x08`
- `READ_REG = 0x0A`
- `SPI_ATTACH = 0x0D`
- `READ_FLASH_SLOW = 0x0E`
- `CHANGE_BAUD = 0x0F`
- `FLASH_BEGIN = 0x02`
- `FLASH_DATA = 0x03`
- `FLASH_END = 0x04`

ESP32 classic ROM dùng checksum XOR bắt đầu từ `0xEF` và block flash 0x400 byte.

## Lưu ý về flash size

v3 **không giả định ESP32 có 4 MB**. Worker đọc JEDEC sau `SPI_ATTACH` để lấy dung lượng Flash thực và dùng dung lượng đó cho `SET_FLASH_PARAMS`.

`esp32_rom.py` vẫn có `READ_FLASH_SLOW` (giới hạn 64 byte mỗi lệnh) nhưng menu v3 chưa nối thao tác readback vì worker chưa hỗ trợ.

## Xóa Flash (mục 8) — xóa toàn bộ chip

Mục `8` xóa **toàn bộ chip** bằng lệnh `ERASE_FLASH` của ROM (giống `erase_flash` chuẩn của esptool):

- Không cần nhập dung lượng, offset hay kích thước.
- Menu yêu cầu xác nhận `C/K` trước khi xóa.
- Toàn bộ dữ liệu trên Flash chuyển thành `0xFF`; thao tác không thể hoàn tác.
- Thời gian xóa có thể từ 30 giây đến vài phút tùy dung lượng chip.

Các preset xóa vùng (`Bootloader`, `Partition table`, `boot_app0`, `Vùng ứng dụng`) vẫn có trong `utils.py` nhưng chưa được nối vào menu v3.

## Sửa lỗi ROM báo `command 0x04: 01060000` khi Xóa Flash

`erase_by_flash_begin()` trước đây gọi `FLASH_BEGIN` rồi gọi thẳng `FLASH_END`, bỏ qua các gói `FLASH_DATA`. ROM ESP32 thật ghi nhận số block đã khai báo trong `FLASH_BEGIN` (`num_blocks`) và chờ nhận đủ từng đó gói `FLASH_DATA` trước khi chấp nhận `FLASH_END` — nhận `FLASH_END` sớm khiến ROM báo lỗi trạng thái `0x06` ("không thực hiện được lệnh nhận"), hiển thị dạng `ESP32 ROM báo lỗi command 0x04: 01060000`.

Đã sửa: sau `FLASH_BEGIN`, gửi đủ số block `FLASH_DATA` toàn byte `0xFF` (khớp trạng thái đã xóa mà `FLASH_BEGIN` vừa tạo ra) rồi mới gọi `FLASH_END`. Có test `tests/test_erase.py` khoá lại đúng thứ tự `begin → data × N → end`.

## BOOT

Nếu DTR/RTS không đưa được chip vào Download Mode:

1. Giữ BOOT.
2. Nhấn EN/RESET.
3. Giữ BOOT 1–2 giây.
4. Thả BOOT.
5. Chạy lại mục `1`.

## Verify

Sau khi nạp, `esp32_flash.py` đọc lại MD5 vùng vừa ghi bằng `SPI_FLASH_MD5`; chỉ khi MD5 khớp mới báo thành công. Menu v3 chưa có mục verify riêng vì worker chưa hỗ trợ thao tác đọc lại toàn vùng.

## Unit tests

```bash
python -m unittest discover -s tests -v
```

## Nguồn protocol

Cấu trúc command, checksum, block 0x400, `FLASH_BEGIN/DATA/END`, `SPI_ATTACH` và ROM `READ_FLASH_SLOW` được đối chiếu với mã nguồn esptool của Espressif. v3 không import esptool và không dùng pyserial.


## Trạng thái v3

- Đã tách hoàn toàn menu và USB worker.
- Menu chạy trực tiếp bằng Python trong Termux.
- Worker chỉ chạy thông qua `termux-usb -E`.
- Worker lấy `TERMUX_USB_FD` từ môi trường.
- Không mở `/dev/bus/usb/...` từ Python.
- CP2102 control transfer + Bulk OUT/IN dùng USBDEVFS.
- ROM implementation hiện tập trung vào **ESP32 classic / ESP32-WROOM-32**. Các ESP32-S2/S3/C3/C6 có ROM protocol khác ở một số phần và không được giả định là ESP32 classic.
- `READ_FLASH_SLOW (0x0E)` giới hạn 64 byte/lệnh theo ROM ESP32 classic nên readback lớn sẽ chậm; menu v3 chưa nối thao tác này.
- Worker tự đọc JEDEC flash size sau `SPI_ATTACH`, không hard-code 4 MB.


## Sửa lỗi `termux-usb: too many arguments`

v3 dùng `termux-usb -E -e run_worker.sh DEVICE` và truyền tham số Worker qua biến môi trường Base64. Không truyền `--op`, `--file`... trực tiếp sau DEVICE. Đây là cách tương thích với callback Termux:API đang dùng trên HONOR X7d.

## Sửa lỗi trình tự BOOT/EN (không tự vào Download Mode)

`bootloader.py` trước đây gọi các bước `set_mhs()` **sai thứ tự**: EN được thả ra khỏi reset (`set_mhs(False, False)`) **trước khi** GPIO0 được kéo xuống thấp (`set_mhs(True, False)`). ESP32 chỉ lấy mẫu strap GPIO0 đúng vào thời điểm EN chuyển từ thấp lên cao (thoát reset) — vì thứ tự cũ sai, chip thường thoát reset với GPIO0 đang ở mức cao và boot thẳng vào firmware thường thay vì ROM Download Mode, nên phải giữ BOOT tay mới nạp được.

Đã sửa lại đúng theo trình tự `UnixTightReset` của esptool: kéo GPIO0 xuống thấp *trước*, giữ nguyên trong lúc thả EN, rồi mới thả GPIO0. Sau bản vá này, mục `1` (kiểm tra kết nối), `3` (thông tin chip) và `4` (đọc MAC) nên tự vào Download Mode mà không cần giữ nút BOOT, miễn mạch auto-reset trên board đúng chuẩn (2 transistor, active-low qua DTR/RTS).

Nếu board vẫn không tự vào được sau bản vá, khả năng cao là mạch auto-reset trên board đảo cực khác chuẩn — giữ BOOT thủ công rồi chạy mục `1` làm phương án dự phòng.


## v3.1 — chẩn đoán SYNC

Đã sửa trình tự DTR/RTS theo Espressif, dọn RX trước SYNC, tiêu thụ các response SYNC dư, hiển thị lỗi SYNC chi tiết và thêm `sync-raw`. Chế độ debug in tối đa 64 byte mỗi USB Bulk TX/RX.

\n## V3 Fixed 4 — Termux callback\n\n
Trên HONOR X7d/Termux hiện tại, `termux-usb -e` truyền USB FD vào
argument cuối của callback nhưng environment của tiến trình gọi không
được bảo đảm truyền sang callback. V3 Fixed 4 không còn phụ thuộc vào
`ESPFLASH_WORKER_ARGS_B64`: mỗi lần flash tạo wrapper tạm chứa các tham
số nghiệp vụ, sau đó `termux-usb` truyền FD vào wrapper và wrapper chuyển
FD cùng các tham số sang `usb_worker.py`. Không sử dụng `-E`.\n

## Fixed 6
Request được ghi atomic vào `.worker_request.json`; request được giữ lại nếu callback/worker thất bại để chẩn đoán. Callback cố định trong `$PREFIX/bin` chuyển FD cuối cùng cho worker.
