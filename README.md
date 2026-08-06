# ESP32 Android Toolkit V2

Nạp firmware ESP32 hoàn toàn trong **Termux** qua cáp OTG, không cần:

- root
- PlatformIO
- Arduino IDE
- adb
- `serial.tools.list_ports` / enumerate `/dev/ttyUSB*`

Hoạt động dựa 100% trên **Android USB Host API** (thông qua `termux-usb`
của gói Termux:API) + `libusb1`, tự triển khai lại giao thức ROM
bootloader của ESP32 và driver cho các chip USB-UART phổ biến bằng
Python thuần.

Hỗ trợ Android 10 → 16. Đã thử trên HONOR MagicOS, và tương thích thiết
kế với Xiaomi HyperOS, Samsung OneUI, OPPO ColorOS, OnePlus OxygenOS,
Pixel Android (mọi ROM có hỗ trợ USB Host / OTG chuẩn AOSP).

## Vì sao có bản V2

Bản V1 dùng cùng nền tảng Android USB Host + termux-usb, nhưng có một
lỗi kiến trúc: bước "chọn thiết bị" xin quyền USB một lần (để đọc
VID/PID lọc chip), rồi bước "thao tác" (flash/monitor/...) xin quyền
**lần thứ hai** cho cùng thiết bị đó. Hai vòng xin quyền tách biệt là
nguyên nhân chính gây lỗi `Permission denied` ngắt quãng — người dùng
thường chỉ để ý bấm "Allow" ở hộp thoại đầu rồi bỏ qua hộp thoại sau,
hoặc phiên quyền hết hạn giữa hai bước.

**V2 sửa tận gốc:** bước chọn thiết bị chỉ dùng `termux-usb -l` (liệt
kê đường dẫn thô, không cần quyền). Toàn bộ phần còn lại — đọc VID/PID,
chọn driver UART, chạy giao thức ROM loader, ghi/xóa/đọc flash — diễn
ra **bên trong một phiên `termux-usb -r -e` DUY NHẤT**. Mỗi lần bạn
chạy `flash.sh`/`erase.sh`/`chipinfo.sh`/`mac.sh`/`monitor.sh`, Android
chỉ hỏi quyền đúng **một lần**.

## Kiến trúc

```
esp32-toolkit/
├── menu.sh              # Menu trung tâm
├── install.sh            # Cài dependency (1 lệnh)
├── doctor.sh              # Chẩn đoán môi trường
├── flash.sh                # Flash firmware
├── erase.sh                # Xóa toàn bộ flash
├── monitor.sh               # Serial monitor
├── chipinfo.sh                # Thông tin chip + MAC + magic register
├── mac.sh                      # Chỉ in MAC
├── update.sh                    # git pull + cập nhật dependency
├── firmware/                     # Đặt file .bin vào đây
│   ├── bootloader.bin
│   ├── boot_app0.bin
│   ├── partitions.bin
│   ├── firmware.bin
│   └── littlefs.bin (tùy chọn)
├── config/
│   ├── config.json          # baudrate, timeout, danh sách chip UART đã biết...
│   └── partition.json       # offset flash mặc định, danh sách file bắt buộc/tùy chọn
├── tools/
│   ├── logger.py            # Log màu ANSI
│   ├── config.py            # Nạp config.json / partition.json
│   ├── progress.py          # Progress bar + spinner
│   ├── utils.py              # format số liệu, retry, kiểm tra file...
│   ├── android_usb.py         # Lớp USB mức thấp (termux-usb + libusb1)
│   ├── usb_bridge.py           # Giao diện UartBridge trừu tượng + factory
│   ├── cp210x.py                 # Driver CP2102/CP2102N/CP2105
│   ├── ch340.py                   # Driver CH340/CH340C/CH9102
│   ├── ftdi.py                     # Driver FT232R/FT231X
│   ├── cdc_acm.py                   # Driver CDC-ACM chuẩn (USB native ESP32-S2/S3/C3/C6/H2)
│   ├── usb_detect.py                 # Liệt kê + chọn thiết bị (KHÔNG xin quyền)
│   ├── esp_loader.py                  # Giao thức SLIP + ROM loader ESP32
│   ├── bootloader.py                   # Ghép USB → UartBridge → EspRomLoader, connect()
│   ├── firmware.py                      # write_flash/erase/verify/read/image_info cấp cao
│   ├── esptool_android.py                # CLI thống nhất (subcommands)
│   ├── serial_monitor.py                  # Serial monitor real-time, auto reconnect
│   └── common.sh                           # Thư viện bash dùng chung
└── README.md
```

### Luồng dữ liệu

```
menu.sh / flash.sh / erase.sh / chipinfo.sh / mac.sh / monitor.sh
        │
        ├─ tools/usb_detect.py  (termux-usb -l, KHÔNG cần quyền)
        │
        └─ termux-usb -r -e "<lệnh python>" <device_path>   ← 1 LẦN DUY NHẤT
                │
                ├─ tools/android_usb.py     (mở fd đã cấp quyền, wrapSysDevice)
                ├─ tools/usb_bridge.py      (chọn driver theo VID/PID)
                │     ├─ cp210x.py / ch340.py / ftdi.py / cdc_acm.py
                ├─ tools/esp_loader.py      (SLIP + giao thức ROM loader)
                ├─ tools/bootloader.py      (connect/sync/detect chip)
                ├─ tools/firmware.py        (flash/erase/verify/read)
                └─ tools/esptool_android.py (CLI gọi tất cả các lớp trên)
```

## Chip ESP32 được hỗ trợ

Tự động nhận diện qua magic register sau khi `sync`:

`ESP32`, `ESP32-S2`, `ESP32-S3`, `ESP32-C2`, `ESP32-C3`, `ESP32-C6`, `ESP32-H2`

## Driver UART-USB được hỗ trợ

| Chip | VID:PID | Driver |
|---|---|---|
| CP2102 / CP2102N | 10C4:EA60 | `cp210x.py` |
| CP2105 | 10C4:EA70 | `cp210x.py` |
| CH340 / CH340C | 1A86:7523 | `ch340.py` |
| CH9102 | 1A86:55D4 | `ch340.py` |
| FT232R | 0403:6001 | `ftdi.py` |
| FT231X | 0403:6015 | `ftdi.py` |
| USB native (ESP32-S2/S3/C3/C6/H2) | 303A:xxxx | `cdc_acm.py` |

Board dùng PL2303 hoặc chip UART khác chưa được liệt kê có thể thêm dễ
dàng bằng cách tạo file driver mới kế thừa `UartBridge` trong
`tools/usb_bridge.py` rồi đăng ký vào `_driver_classes()`.

## Cài đặt

```bash
pkg install git -y
git clone <repo-url> esp32-toolkit && cd esp32-toolkit
bash install.sh
```

`install.sh` tự cài: `python`, `clang`, `make`, `cmake`, `termux-api`,
`jq`, `libusb`, và thư viện Python `libusb1`.

Sau khi cài, bạn cần cài thêm ứng dụng **Termux:API** (F-Droid hoặc
Google Play) — đây là phần bắt buộc để `termux-usb` hoạt động.

## Sử dụng

Cách đơn giản nhất — dùng menu:

```bash
./menu.sh
```

Hoặc gọi trực tiếp từng script:

```bash
./doctor.sh      # kiểm tra môi trường trước
./flash.sh        # nạp firmware/*.bin vào ESP32 qua OTG
./erase.sh          # xóa toàn bộ flash
./chipinfo.sh          # xem chip, MAC, magic register
./mac.sh                 # chỉ in MAC
./monitor.sh                # serial monitor, Ctrl+C để thoát
./update.sh                    # cập nhật toolkit
```

### Flash

Đặt file `.bin` vào thư mục `firmware/` (đã có sẵn ví dụ), sau đó:

```bash
./flash.sh
```

Biến môi trường tùy chỉnh:

```bash
FLASH_BAUD=115200 ./flash.sh          # baud thấp hơn nếu cáp/board không ổn định
LITTLEFS_OFFSET=0x290000 ./flash.sh   # đổi offset LittleFS (partition scheme khác)
MAX_RETRIES=5 ./flash.sh              # tăng số lần thử lại
```

Offset mặc định (theo `min_spiffs.csv`, flash 4MB, arduino-esp32):

| Phần | Offset |
|---|---|
| bootloader.bin | `0x1000` |
| partitions.bin | `0x8000` |
| boot_app0.bin | `0xe000` |
| firmware.bin | `0x10000` |
| littlefs.bin (tùy chọn) | `0x3D0000` (hoặc `0x290000` nếu dùng scheme 8MB) |

Có thể sửa trực tiếp trong `config/partition.json` nếu muốn thay đổi
lâu dài thay vì truyền biến môi trường mỗi lần.

### Monitor

```bash
./monitor.sh
BAUD=921600 ./monitor.sh
LOG_FILE=session.log ./monitor.sh
FILTER='ERROR' ./monitor.sh
```

### Dùng trực tiếp CLI Python (nâng cao)

```bash
python3 tools/esptool_android.py image_info firmware/firmware.bin
# Các subcommand khác (sync/chip_id/read_mac/flash_id/erase_flash/
# write_flash/flash_auto/read_flash/verify_flash/reset) đều cần chạy
# bên trong một phiên termux-usb -r -e, xem cách flash.sh gọi.
```

## Cấu hình (`config/`)

- **`config.json`**: baudrate mặc định (reset/flash/monitor), số lần
  retry, timeout xin quyền USB, danh sách chip UART đã biết (VID:PID
  → tên hiển thị), danh sách chip ESP32 được hỗ trợ.
- **`partition.json`**: offset flash mặc định cho từng phần
  (bootloader/partitions/boot_app0/firmware/littlefs), đường dẫn file
  tương ứng trong `firmware/`, và danh sách file bắt buộc/tùy chọn.

Sửa 2 file này để tùy biến toolkit mà không cần đụng vào code Python.

## Doctor — chẩn đoán

```bash
./doctor.sh
```

Kiểm tra: Python, phiên bản Android, USB Host/OTG, `termux-api`, thư
viện `libusb1`, file firmware, file cấu hình, và thiết bị USB đang cắm
(chỉ liệt kê, không xin quyền).

## Troubleshooting

**"Permission denied" khi flash**
Đây chính là lỗi kiến trúc mà V2 khắc phục. Nếu vẫn gặp: đảm bảo bạn
đang dùng V2 (chỉ có DUY NHẤT một hộp thoại xin quyền USB xuất hiện
mỗi lần chạy lệnh). Nếu hộp thoại không hiện ra, kiểm tra ứng dụng
Termux:API đã cài và Termux có quyền hiển thị overlay/notification.

**Không tìm thấy thiết bị USB**
- Cáp OTG phải hỗ trợ truyền dữ liệu (nhiều cáp OTG rẻ chỉ hỗ trợ sạc).
- Điện thoại phải hỗ trợ USB Host (đa số flagship có, một số máy giá
  rẻ không có).
- Thử `./doctor.sh` để xem `termux-usb -l` có trả về gì không.

**Sync/connect thất bại (không dò được ROM bootloader)**
- Một số board clone không tự động vào chế độ download qua DTR/RTS —
  giữ nút `BOOT`/`IO0` khi cắm cáp, thả ra sau khi thấy log "Đang kết
  nối...".
- Thử `FLASH_BAUD=115200 ./flash.sh` nếu board/cáp không ổn định ở
  baud cao.

**Không hỗ trợ chip USB-UART**
Kiểm tra VID/PID board của bạn (thường in trên chip hoặc tra theo tên
chip) và so với bảng driver ở trên. Nếu chip chưa được hỗ trợ, có thể
thêm driver mới theo mẫu `tools/cp210x.py`.

**CDC-ACM (ESP32-S2/S3/C3/C6/H2 dùng cổng USB native) không nhận dữ liệu**
Một số firmware chỉ xuất log ra cổng USB-CDC khi DTR được bật —
`cdc_acm.py` đã tự bật DTR+RTS khi mở, nhưng nếu firmware dùng
USB-Serial-JTAG (không phải USB-CDC), hãy kiểm tra `idf.py menuconfig`
→ Component config → ESP System Settings → Channel for console output
được đặt đúng cổng.

## FAQ

**Có cần root không?** Không. Toàn bộ dựa trên Android USB Host API
chuẩn của Termux:API, không truy cập `/dev/bus/usb/*` trực tiếp bằng
quyền hệ thống.

**Có cần cài PlatformIO/Arduino IDE trên máy tính không?** Không, chỉ
cần biên dịch firmware `.bin` từ máy tính (hoặc CI) một lần rồi copy
`.bin` vào điện thoại; toolkit chỉ lo phần nạp qua OTG.

**Toolkit có tự build firmware từ source `.ino`/`.py` không?** Không.
Toolkit chỉ nạp file `.bin` đã biên dịch sẵn (đặt vào `firmware/`).

**Vì sao không dùng lại `esptool.py` gốc?** `esptool.py` gốc dùng
pySerial, cần `/dev/ttyUSB*` — thứ mà sandbox Android không cấp cho
ứng dụng thông thường. Toolkit triển khai lại đúng giao thức ROM
loader công khai của Espressif bằng Python thuần trên nền Android USB
Host API.

## Đã kiểm thử

ESP32 DevKit V1 (CP2102) qua cáp OTG trên **HONOR X7d chạy MagicOS 9**.
