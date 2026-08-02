# ESP32 Android Toolkit — Flash/Erase/Monitor ESP32 hoàn toàn trên điện thoại

Bộ công cụ này cho phép bạn **build, flash, erase, đọc thông tin chip,
đọc MAC, và mở Serial Monitor cho ESP32/ESP8266 trực tiếp trên điện
thoại Android qua Termux — không cần máy tính, không cần PlatformIO**.

Hỗ trợ Android 10 → 15, Termux (bản F-Droid), Python 3.14, kết nối qua
cáp OTG + USB Host của điện thoại.

---

## 1. Vì sao không dùng PlatformIO / esptool gốc?

`esptool.py` gốc và PlatformIO dùng `pyserial` để enumerate cổng
`/dev/ttyUSB*`, `/dev/ttyACM*` — điều này **không hoạt động trên
Android** vì hệ điều hành sandbox không cho ứng dụng thường (kể cả
Termux) liệt kê hay mở trực tiếp các file thiết bị trong `/dev`.

Bộ công cụ này viết lại hoàn toàn phần giao tiếp USB, đi qua
**Android USB Host API** thông qua lệnh `termux-usb` (gói
`termux-api`), rồi tự triển khai giao thức UART (SLIP) và giao thức
ROM bootloader của ESP32 bằng Python thuần + `libusb1`.

Kết quả: không còn lỗi kiểu:

```
ImportError: Sorry: no implementation for your platform ('posix')
```

hoặc

```
don't know how to enumerate ttys on this system.
```

---

## 2. Cài đặt

### Bước 1: Cài Termux

Cài **Termux** và **Termux:API** từ [F-Droid](https://f-droid.org)
(khuyến nghị, không dùng bản Google Play vì đã ngừng cập nhật).

### Bước 2: Clone hoặc giải nén dự án

```bash
git clone https://github.com/khahdihdz/esp32-toolkit
cd esp32-toolkit
```

### Bước 3: Chạy install.sh

```bash
chmod +x *.sh
./install.sh
```

Script sẽ tự động:

- Cập nhật & nâng cấp gói Termux
- Cài `git, python, clang, make, cmake, termux-api, jq, unzip, wget, curl, coreutils, usbutils, libusb`
- Nâng cấp `pip`
- Cài thư viện Python `libusb1`
- Kiểm tra lại toàn bộ môi trường

### Bước 4: Cấp quyền cho Termux:API

Mở ứng dụng **Termux:API** ít nhất 1 lần và cấp mọi quyền được yêu cầu
(đặc biệt là quyền hiển thị thông báo, cần cho hộp thoại xin quyền
USB).

---

## 3. Chuẩn bị firmware

Đặt 4 file sau vào thư mục `firmware/` (bắt buộc):

```
firmware/bootloader.bin
firmware/partitions.bin
firmware/boot_app0.bin
firmware/firmware.bin
```

Nếu project của bạn có dùng LittleFS/SPIFFS (ví dụ dashboard web đọc file
từ `data/`), thêm file thứ 5 (tùy chọn — `flash.sh` sẽ tự phát hiện):

```
firmware/littlefs.bin
```

Offset mặc định để flash `littlefs.bin` là `0x3D0000` (đúng cho partition
scheme `min_spiffs.csv` của arduino-esp32). Nếu project dùng partition
scheme khác, ghi đè bằng biến môi trường, ví dụ:

```bash
LITTLEFS_OFFSET=0x290000 ./flash.sh   # default.csv (4MB, spiffs 0x290000)
```

Bạn có thể lấy các file này bằng cách:

- Tải artifact từ GitHub Actions (workflow tự build khi bạn push code
  vào `main`/`master`, xem `.github/workflows/build.yml`)
- Build bằng ESP-IDF hoặc Arduino IDE trên máy tính rồi copy sang máy

---

## 4. Sử dụng

### Kiểm tra môi trường

```bash
./doctor.sh
```

Kiểm tra Python, Android version, USB Host, OTG, Termux:API, firmware,
quyền USB và thiết bị đang cắm. Nếu có lỗi, doctor.sh sẽ giải thích rõ
nguyên nhân và cách khắc phục.

### Flash firmware

```bash
./flash.sh
```

Script sẽ:

1. Tự phát hiện ESP32 qua USB (hiện menu nếu có nhiều thiết bị)
2. Xin quyền USB từ Android (xác nhận hộp thoại trên màn hình)
3. Kiểm tra đủ 4 file firmware
4. Flash lần lượt `bootloader.bin → 0x1000`, `partitions.bin → 0x8000`,
   `boot_app0.bin → 0xe000`, `firmware.bin → 0x10000`, và
   `littlefs.bin → $LITTLEFS_OFFSET` (mặc định `0x3D0000`) **nếu file này tồn tại**
5. Hiển thị %, tốc độ, dung lượng, ETA cho từng file
6. Tự động thử lại tối đa 3 lần nếu gặp lỗi
7. Reset ESP32 sau khi flash xong và hiển thị tổng thời gian

Đổi tốc độ baud khi flash (mặc định `460800`):

```bash
FLASH_BAUD=115200 ./flash.sh
```

### Xóa toàn bộ flash

```bash
./erase.sh
```

### Xem thông tin chip

```bash
./chipinfo.sh
```

Hiển thị: Chip, Revision, Crystal, MAC, Flash Size, Flash Mode, Flash
Speed, Features.

### Đọc địa chỉ MAC

```bash
./mac.sh
```

In:

```
MAC:
AA:BB:CC:DD:EE:FF
```

### Serial Monitor

```bash
./monitor.sh
```

Tùy chọn:

```bash
BAUD=921600 ./monitor.sh              # đổi baud
LOG_FILE=session.log ./monitor.sh     # lưu log ra file
FILTER='ERROR' ./monitor.sh           # chỉ hiện dòng khớp regex
```

Nhấn `Ctrl+C` để thoát. Có timestamp, màu theo mức log (E/W/I của
ESP-IDF), UTF-8, và tự động kết nối lại nếu mất kết nối USB.

### Cập nhật dự án

```bash
./update.sh
```

---

## 5. Cấp quyền USB trên Android

Mỗi lần chạy `flash.sh`, `erase.sh`, `chipinfo.sh`, `mac.sh`, hoặc
`monitor.sh`, Android sẽ hiện **hộp thoại xin quyền truy cập USB**.
Bạn cần:

1. Nhấn vào thông báo (hoặc mở lại app nếu popup bị ẩn)
2. Chọn **"OK"/"Cho phép"**
3. Tick vào **"Sử dụng theo mặc định cho thiết bị này"** để không phải
   xác nhận lại mỗi lần (không bắt buộc)

Nếu popup không hiện, hãy đảm bảo Termux:API đã được cấp quyền thông
báo (Settings → Apps → Termux:API → Notifications → Allow).

---

## 6. Chip và USB-UART được hỗ trợ

**Chip ESP:** ESP8266, ESP32, ESP32-S2, ESP32-S3, ESP32-C2, ESP32-C3,
ESP32-C6, ESP32-H2 (nhận diện tự động qua thanh ghi magic number; các
biến thể ROM chưa có trong bảng sẽ được báo là "không xác định" kèm
giá trị magic để bạn có thể bổ sung vào `tools/android_esptool.py`).

**USB-UART:** CP2102/CP2102N, CH340/CH340C, CH9102, FT232/FT231X,
PL2303.

---

## 7. Kiến trúc dự án

```
project/
├── firmware/                  # Đặt 4 file .bin (+ littlefs.bin tùy chọn) vào đây trước khi flash
├── tools/
│   ├── android_esptool.py     # Giao thức SLIP + ESP ROM bootloader (core)
│   ├── android_usb_raw.py     # Lớp USB mức thấp (libusb1 qua fd của termux-usb)
│   ├── uart_bridge.py         # Driver CP210x/CH340/FT232/PL2303
│   ├── usb_helper.py          # Liệt kê & xin quyền USB qua termux-usb
│   ├── select_device.py       # Chọn thiết bị (dùng bởi common.sh)
│   ├── serial_monitor.py      # Serial Monitor
│   ├── chipinfo.py / mac.py   # Wrapper hiển thị thông tin
│   ├── logger.py              # Log màu ANSI
│   ├── utils.py                # Progress bar, retry, format, v.v.
│   └── common.sh              # Thư viện bash dùng chung
├── flash.sh / erase.sh / chipinfo.sh / mac.sh / monitor.sh
├── install.sh / doctor.sh / update.sh
└── .github/workflows/build.yml
```

---

## 8. Troubleshooting

| Vấn đề | Nguyên nhân thường gặp | Cách khắc phục |
|---|---|---|
| Không phát hiện thiết bị USB | Cáp chỉ hỗ trợ sạc, không hỗ trợ data | Đổi cáp OTG hỗ trợ truyền dữ liệu |
| `termux-usb: command not found` | Chưa cài `termux-api` | `pkg install termux-api` + cài app Termux:API |
| Không hiện popup xin quyền | Termux:API chưa được cấp quyền thông báo | Vào Settings → Apps → Termux:API → cấp quyền |
| `Không thể kết nối với ESP32` | Board chưa vào chế độ nạp | Giữ nút BOOT/IO0 khi cắm cáp, hoặc dùng board có auto-reset |
| Flash bị lỗi giữa chừng | Baudrate quá cao cho cáp/board | `FLASH_BAUD=115200 ./flash.sh` |
| `Không hỗ trợ chip USB-UART...` | Board dùng chip lạ | Thêm VID/PID vào `uart_bridge.py` và `usb_helper.py` |
| Không parse được `termux-usb -l` | Chưa cắm thiết bị hoặc quyền OTG bị chặn hệ thống | Kiểm tra `lsusb`, thử cáp/adapter khác |

---

## 9. FAQ

**Có cần root máy không?**
Không. Toàn bộ luồng dùng Android USB Host API chính thức qua
Termux:API, không cần root.

**Vì sao không dùng luôn pySerial?**
Vì Android sandbox chặn truy cập `/dev/ttyUSB*`/`/dev/ttyACM*` với
ứng dụng thông thường; chỉ có Android USB Host API (qua `termux-usb`)
được phép, và API đó chỉ cấp raw USB access, không cấp giao diện tty —
nên phải tự triển khai giao thức UART qua USB thay vì dùng pySerial.

**Có build firmware trực tiếp trên điện thoại được không?**
Được, nếu bạn cài ESP-IDF trong Termux (khá nặng và cần proot hoặc
container). Cách khuyến nghị và ổn định hơn là để GitHub Actions build
sẵn rồi tải file `.bin` xuống điện thoại.

**Flash được ESP8266 không?**
Được, giao thức SLIP + ROM loader tương tự ESP32, chỉ khác offset ghi
flash tùy theo file/board của bạn.

**Có hỗ trợ nhiều board cắm cùng lúc không?**
Có. Nếu có nhiều thiết bị USB, script sẽ hiện menu để bạn chọn.

---

## 10. Giấy phép

Dự án tự phát triển cho mục đích cá nhân/học tập. Giao thức SLIP và
ROM bootloader của ESP32 là giao thức công khai do Espressif tài liệu
hóa.
