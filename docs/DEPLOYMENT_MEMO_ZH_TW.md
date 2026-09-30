# Raspberry Pi 5 AutoCAR + YOLO26 完整開發與部署備忘錄

> 2026-09-29：安裝器已支援任意既有非 root 帳號與 hostname。請先閱讀[通用安裝說明](PORTABLE_INSTALL_ZH_TW.md)；本文的 rpi5 帳號、家目錄及 IP 為原測試機範例，服務模板請由安裝器產生。

最後更新：2026-09-16；本次板端更新及驗證紀錄見第 26 節。

若是第一次從硬體、作業系統開始製作，建議先依序閱讀
[`IMPLEMENTATION_TUTORIAL_ZH_TW.md`](IMPLEMENTATION_TUTORIAL_ZH_TW.md)，再使用本備忘錄
查閱部署參數、效能與故障案例。

本文件是一份可從零開始實作的逐步教學，目標是在 Raspberry Pi 5 上部署本專案，並在 Windows 瀏覽器透過區域網路完成：

- YOLO26 NCNN 即時物件辨識與畫框串流
- Raspberry Pi CSI Camera 或外接 USB Webcam
- PCA9685 四輪馬達控制
- 雙軸相機雲台控制
- H.264 錄影
- 手動方向控制與安全 watchdog
- 選配的車道辨識、交通號誌辨識與自動駕駛
- `systemd` 開機自動啟動及服務管理

> 本文件的預設帳號為 `rpi5`、Pi 位址範例為 `192.168.0.160`、專案服務端口為 `8000`。實作時必須將 IP 位址換成你的實際值。若登入帳號不是 `rpi5`，還需要同步修改服務檔及路徑。

---

## 1. 完成後的系統架構

```text
CSI Camera / USB Webcam
          │
          ▼
      Picamera2
          │
          ├── 原始影像擷取
          ├── H.264 錄影
          └── YOLO26 NCNN 推論
                    │
                    ▼
          JPEG 畫框影像串流
                    │
                    ▼
        AutoCAR HTTP Server :8000
          │        │        │
          │        │        └── 自動駕駛狀態
          │        └─────────── 雲台／錄影 API
          └──────────────────── 車體控制 API
                    │
                    ▼
          Windows Chrome / Edge
```

執行中的主要路徑如下：

| 項目 | 路徑或位址 |
|---|---|
| 正式程式 | `/opt/autocar` |
| Python 虛擬環境 | `/opt/autocar-venv` |
| 系統設定 | `/etc/autocar.env` |
| systemd 服務 | `/etc/systemd/system/autocar.service` |
| 模型目錄 | `/opt/autocar/models` |
| 錄影目錄 | `/home/rpi5/Videos/autocar` |
| Web UI | `http://<Pi-IP>:8000` |
| 狀態 API | `http://<Pi-IP>:8000/api/status` |
| 即時影像串流（原始／畫框由開關控制） | `http://<Pi-IP>:8000/api/camera/stream` |

---

## 2. 安全須知

在操作馬達之前務必遵守：

1. 第一次測試時將車輪架空。
2. 馬達和伺服器不要直接使用 Raspberry Pi 的 5V 供電。
3. 馬達電源與 Pi 電源應分開，但控制系統必須共地。
4. 準備實體斷電或急停方式。
5. 測試方向前將 `AUTOCAR_MANUAL_SPEED` 設為低速，例如 `25`。
6. 網頁失去連線時，watchdog 應在設定時間內停止馬達。
7. 自動駕駛必須在手動模式、相機、模型及急停都驗證後才啟用。
8. 本 Web UI 沒有使用者登入功能，只能在可信任的區域網路使用，不可直接將端口轉發到公網。

---

## 3. 硬體需求

### 3.1 基本硬體

- Raspberry Pi 5，建議 8 GB；4 GB 也可執行 YOLO26n
- 官方 27W USB-C 電源，5V/5A
- Raspberry Pi 5 Active Cooler 或可靠的主動散熱
- 32 GB 以上高品質 microSD，或使用 NVMe
- Raspberry Pi Camera 或 USB Webcam
- PCA9685 馬達／伺服控制板
- 獨立馬達電源
- 四輪底盤、馬達驅動及雙軸雲台（依專案硬體）

### 3.2 本專案預設 PCA9685 配置

| 功能 | 通道／接腳 |
|---|---|
| PCA9685 I²C 位址 | `0x40` |
| I²C bus | `1` |
| 馬達 A PWM | PCA9685 channel `0` |
| 馬達 B PWM | PCA9685 channel `5` |
| 馬達 C PWM | PCA9685 channel `6` |
| 馬達 D PWM | PCA9685 channel `11` |
| 馬達 D 方向 | BCM GPIO `25`、`24` |
| 雲台水平 Pan | PCA9685 channel `12` |
| 雲台俯仰 Tilt | PCA9685 channel `13` |

接線前應以實際馬達控制板原理圖為準。不同廠牌的方向腳位可能相反。

---

## 4. 安裝 Raspberry Pi OS

### 4.1 使用 Raspberry Pi Imager

在 Windows 安裝並開啟 Raspberry Pi Imager：

1. 選擇 Raspberry Pi 5。
2. 選擇 Raspberry Pi OS 64-bit。
3. 建議使用含桌面的版本進行初期硬體測試；正式車載也可使用 Lite。
4. 在進階設定中設定：
   - Hostname：`rpi5`
   - 使用者：`rpi5`
   - 密碼：自行設定強密碼
   - Wi-Fi SSID 與密碼
   - 時區：`Asia/Taipei`
   - 啟用 SSH
5. 寫入 microSD，完成後插入 Pi 5 並開機。

### 4.2 從 Windows 連線

先嘗試 hostname：

```powershell
ssh rpi5@rpi5.local
```

若無法解析 hostname，可從路由器或手機熱點查出 IP，然後使用：

```powershell
ssh rpi5@192.168.0.160
```

登入後確認系統：

```bash
uname -a
uname -m
cat /etc/os-release
hostname -I
```

架構必須顯示：

```text
aarch64
```

---

## 5. 更新系統與準備基礎工具

在 Pi 執行：

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

重新 SSH 登入後安裝工具：

```bash
sudo apt install -y \
  git \
  unzip \
  curl \
  i2c-tools \
  v4l-utils \
  python3-venv \
  python3-pip \
  python3-picamera2 \
  python3-opencv \
  python3-numpy \
  python3-gpiozero \
  python3-smbus
```

Raspberry Pi OS Bookworm 之後不建議把套件直接安裝到系統 Python。本專案會建立 `/opt/autocar-venv`，並以 `--system-site-packages` 存取 apt 管理的 Picamera2/libcamera。

---

## 6. 測試相機

### 6.1 CSI Camera

關機後接上 CSI 相機。Pi 5 的 CSI 接頭尺寸與部分舊款 Pi 不同，必須使用正確排線。

開機後列出相機：

```bash
rpicam-hello --list-cameras
```

執行五秒測試：

```bash
rpicam-hello --camera 0 --timeout 5000
```

無桌面環境使用：

```bash
rpicam-hello --camera 0 --nopreview --timeout 5000
```

### 6.2 USB Webcam

列出 V4L2 裝置：

```bash
v4l2-ctl --list-devices
```

查看某一裝置支援格式：

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

使用 Picamera2 列出相機索引：

```bash
python3 - <<'PY'
from picamera2 import Picamera2

for index, info in enumerate(Picamera2.global_camera_info()):
    print("Camera index:", index)
    print(info)
    print()
PY
```

常見情況是 CSI 相機為 `0`、USB Webcam 為 `1`，但必須以實際輸出為準。

### 6.3 相機被占用

若出現：

```text
Device or resource busy
Pipeline handler in use by another process
```

檢查占用者：

```bash
ps -eo pid,user,cmd | grep -E '[r]picam|[l]ibcamera|[p]ython.*(camera|picamera)'
sudo fuser -v /dev/video* /dev/media*
```

先正常停止相關服務：

```bash
sudo systemctl stop autocar.service
```

或對確認過的 PID 執行：

```bash
kill <PID>
```

不要同時執行 `rpicam-hello`、`yolo_web_stream.py` 與 `autocar.service`。

---

## 7. 測試 I²C 與 PCA9685

執行：

```bash
sudo i2cdetect -y 1
```

正常情況應在表格中看到：

```text
40
```

若完全看不到 `0x40`：

1. 關閉電源。
2. 檢查 SDA、SCL、GND 與電壓。
3. 確認 PCA9685 位址跳線。
4. 確認 I²C 已啟用。

可用設定工具啟用 I²C：

```bash
sudo raspi-config
```

選擇 `Interface Options` → `I2C` → `Enable`，再重新開機。

---

## 8. 從 Windows 傳送專案

整合套件位於 Windows：

```text
C:\Users\TTU_SE\Documents\ChatGPT\RPI5_AutoCAR\RPI5_AutoCAR-YOLO-integrated.zip
```

PowerShell 執行：

```powershell
scp "C:\Users\TTU_SE\Documents\ChatGPT\RPI5_AutoCAR\RPI5_AutoCAR-YOLO-integrated.zip" `
  rpi5@192.168.0.160:/home/rpi5/
```

在 Pi 建立新的解壓縮目錄：

```bash
mkdir -p ~/RPI5_AutoCAR_integrated
unzip -o ~/RPI5_AutoCAR-YOLO-integrated.zip -d ~/RPI5_AutoCAR_integrated
```

確認：

```bash
cd ~/RPI5_AutoCAR_integrated
ls
```

應看到：

```text
autocar  deploy  docs  scripts  tests  training  web
README.md  requirements.txt  requirements-autonomy.txt
```

---

## 9. 安裝整合服務

如果舊服務正在運行，先停止：

```bash
sudo systemctl disable --now autocar.service 2>/dev/null || true
```

執行安裝：

```bash
cd ~/RPI5_AutoCAR_integrated
chmod +x scripts/install_pi.sh
sudo ./scripts/install_pi.sh
```

安裝腳本會：

1. 安裝 Raspberry Pi 相機、GPIO、I²C 與 Python 套件。
2. 複製 `autocar/` 與 `web/` 到 `/opt/autocar`。
3. 安裝 `autocar.service`。
4. 首次安裝時建立 `/etc/autocar.env`。
5. 建立 `/opt/autocar-venv`。
6. 在虛擬環境安裝一致的 NumPy/SciPy。
7. 從 PyTorch CPU wheel repository 安裝 CPU 版 PyTorch。
8. 安裝 Ultralytics 與 NCNN Python runtime。
9. 驗證 NumPy、OpenCV、PyTorch、NCNN、Ultralytics 可同時載入。
10. 啟用並立即啟動服務。

> 更新安裝時不會覆寫既有 `/etc/autocar.env`，避免硬體校正值被重設。因此新增設定欄位需手動合併。

---

## 10. 準備 YOLO26 預覽模型

### 10.1 建立暫時開發環境

若尚未產生模型，可在 Pi 使用獨立開發環境：

```bash
mkdir -p ~/autocar
cd ~/autocar

python3 -m venv --system-site-packages .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install --upgrade --no-cache-dir numpy scipy
python -m pip install torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install ultralytics
python -m pip install --upgrade --no-cache-dir ncnn
```

驗證：

```bash
python - <<'PY'
import platform
import numpy
import torch
import torchvision
import ultralytics
import ncnn

print("Machine:", platform.machine())
print("NumPy:", numpy.__version__, numpy.__file__)
print("NCNN: installed")
print("PyTorch:", torch.__version__)
print("Torchvision:", torchvision.__version__)
print("CUDA available:", torch.cuda.is_available())
print("Ultralytics:", ultralytics.__version__)
PY
```

Pi 5 正常應顯示：

```text
Machine: aarch64
PyTorch: ...+cpu
CUDA available: False
```

`CUDA available: False` 是正常結果，因為 Raspberry Pi 5 沒有 NVIDIA CUDA GPU。

### 10.2 下載並測試 YOLO26n

```bash
cd ~/autocar
source .venv/bin/activate

yolo predict \
  model=yolo26n.pt \
  source=https://ultralytics.com/images/bus.jpg \
  device=cpu
```

### 10.3 匯出 NCNN 640 模型

```bash
yolo export \
  model=yolo26n.pt \
  format=ncnn \
  imgsz=640 \
  batch=1 \
  device=cpu
```

輸出目錄：

```text
~/autocar/yolo26n_ncnn_model/
```

至少應包含：

```text
metadata.yaml
model.ncnn.param
model.ncnn.bin
```

測試 NCNN：

```bash
yolo predict \
  model=yolo26n_ncnn_model \
  source=bus.jpg \
  imgsz=640
```

### 10.4 固定輸入尺寸的重要規則

NCNN 模型具有固定輸入尺寸：

- 用 `imgsz=640` 匯出的模型，服務必須設定 `AUTOCAR_PREVIEW_IMGSZ=640`。
- 需要 416 時，必須另外匯出 416 模型。
- 不要拿 640 NCNN 模型直接以 416 推論；原生推論可能錯誤或崩潰。

新版 `DetectionStream` 會在載入原生 runtime 前讀取模型目錄的 `metadata.yaml`。例如模型
記錄為 `320 × 320`，但 `/etc/autocar.env` 設為 `640`，API 會直接回傳：

```text
NCNN input mismatch: model=320x320, AUTOCAR_PREVIEW_IMGSZ=640
```

此時推論維持關閉並使用原始相機串流，不會繼續呼叫尺寸不匹配的 NCNN 模型。

建立獨立的 416 模型：

```bash
cp yolo26n.pt yolo26n_416.pt

yolo export \
  model=yolo26n_416.pt \
  format=ncnn \
  imgsz=416 \
  batch=1 \
  device=cpu
```

預期輸出：

```text
yolo26n_416_ncnn_model
```

### 10.5 如何確認目前 NCNN 尺寸

本專案預設的 YOLO26n NCNN 模型與服務設定目前都是 **640 × 640**。請同時檢查模型
中繼資料及 systemd 環境設定，不要只看其中一項：

```bash
grep -E 'imgsz|img_size' \
  /opt/autocar/models/yolo26n_ncnn_model/metadata.yaml

grep '^AUTOCAR_PREVIEW_IMGSZ=' /etc/autocar.env
```

兩邊都應顯示 `640`。如果模型目錄名稱沒有標示尺寸，應以 `metadata.yaml` 為準。

### 10.6 建立 320、256 或 128 模型

降低輸入尺寸必須從原始 `.pt` 模型重新匯出。不要只把
`AUTOCAR_PREVIEW_IMGSZ=640` 改成 `128`，否則 NCNN 固定輸入形狀不一致，可能造成推論
錯誤、`Bus error` 或服務退出。

建議先建立 **320 × 320** 版本；它通常比 128 更能保留遠處交通燈、停止標誌及小物件：

```bash
cd ~/autocar
source .venv/bin/activate

cp yolo26n.pt yolo26n_320.pt
yolo export \
  model=yolo26n_320.pt \
  format=ncnn \
  imgsz=320 \
  batch=1 \
  device=cpu
```

需要比較 256 或 128 時，分別建立獨立模型：

```bash
cp yolo26n.pt yolo26n_256.pt
yolo export model=yolo26n_256.pt format=ncnn imgsz=256 batch=1 device=cpu

cp yolo26n.pt yolo26n_128.pt
yolo export model=yolo26n_128.pt format=ncnn imgsz=128 batch=1 device=cpu
```

預期輸出目錄分別為：

```text
yolo26n_320_ncnn_model
yolo26n_256_ncnn_model
yolo26n_128_ncnn_model
```

部署 320 版本的完整目錄：

```bash
sudo systemctl stop autocar.service
sudo cp -a ~/autocar/yolo26n_320_ncnn_model /opt/autocar/models/
sudo chown -R rpi5:rpi5 /opt/autocar/models/yolo26n_320_ncnn_model
sudo nano /etc/autocar.env
```

將兩個欄位成對修改：

```ini
AUTOCAR_PREVIEW_MODEL=models/yolo26n_320_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=320
```

然後重新啟動並檢查：

```bash
sudo systemctl start autocar.service
sudo journalctl -u autocar.service -n 100 --no-pager
```

若改用 256 或 128，模型目錄與 `AUTOCAR_PREVIEW_IMGSZ` 也必須一起改成相同尺寸。

---

## 11. 將模型部署至正式服務

建立模型目錄並複製完整 NCNN 目錄：

```bash
sudo mkdir -p /opt/autocar/models

sudo cp -a \
  ~/autocar/yolo26n_ncnn_model \
  /opt/autocar/models/

sudo chown -R rpi5:rpi5 /opt/autocar/models
```

確認：

```bash
ls -la /opt/autocar/models/yolo26n_ncnn_model
```

測試正式服務環境能載入模型：

```bash
/opt/autocar-venv/bin/python - <<'PY'
from ultralytics import YOLO

model = YOLO("/opt/autocar/models/yolo26n_ncnn_model")
print("YOLO26 NCNN model: READY")
PY
```

---

## 12. 設定 `/etc/autocar.env`

編輯：

```bash
sudo nano /etc/autocar.env
```

### 12.1 建議的 CSI Camera 初始設定

```ini
AUTOCAR_HOST=0.0.0.0
AUTOCAR_PORT=8000

AUTOCAR_GPIO=pca9685
AUTOCAR_MANUAL_SPEED=25
AUTOCAR_WATCHDOG_SECONDS=0.8
AUTOCAR_DIRECTION_CHANGE_DELAY=0.15

AUTOCAR_RECORDINGS=/home/rpi5/Videos/autocar
AUTOCAR_CAMERA_INDEX=0
AUTOCAR_CAMERA_ROTATE_180=1

AUTOCAR_PREVIEW_MODEL=models/yolo26n_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=640
AUTOCAR_PREVIEW_CONFIDENCE=0.40
AUTOCAR_PREVIEW_MAX_DET=20
AUTOCAR_PREVIEW_JPEG_QUALITY=65

AUTOCAR_GIMBAL=pca9685
AUTOCAR_GIMBAL_STEP=10
AUTOCAR_PAN_MIN=-80
AUTOCAR_PAN_MAX=80
AUTOCAR_TILT_MIN=-80
AUTOCAR_TILT_MAX=80
AUTOCAR_PAN_CENTER=0
AUTOCAR_TILT_CENTER=-80
AUTOCAR_PAN_INVERT=0
AUTOCAR_TILT_INVERT=1
AUTOCAR_TILT_LOGICAL_MIN=-40
AUTOCAR_TILT_LOGICAL_MAX=10

AUTOCAR_I2C_BUS=1
AUTOCAR_PCA9685_ADDRESS=0x40
AUTOCAR_PAN_CHANNEL=12
AUTOCAR_TILT_CHANNEL=13

AUTOCAR_MODEL=models/traffic_best_ncnn_model
AUTOCAR_LANE_MODEL=models/lane_best_ncnn_model
AUTOCAR_LANE_BACKEND=auto
AUTOCAR_INFERENCE_IMGSZ=416
AUTOCAR_TRAFFIC_CONFIDENCE=0.45
AUTOCAR_TRAFFIC_HISTORY=5
AUTOCAR_TRAFFIC_VOTES=3
AUTOCAR_TRAFFIC_REQUIRED=1
AUTOCAR_LANE_REQUIRED=1
AUTOCAR_LANE_ROI_START=0.55
AUTOCAR_LANE_CLASS=lane
AUTOCAR_AUTO_SPEED=0.42
AUTOCAR_AUTO_SLOW_SPEED=0.22
AUTOCAR_LANE_KP=0.0030
AUTOCAR_LANE_KI=0.00002
AUTOCAR_LANE_KD=0.0010
AUTOCAR_LANE_MIN_CONFIDENCE=0.3
AUTOCAR_TRAFFIC_STALE_SECONDS=1.0
```

儲存 nano：

1. `Ctrl+O`
2. Enter
3. `Ctrl+X`

### 12.2 只測試手動控制

若尚未部署交通與車道模型，暫時設定：

```ini
AUTOCAR_TRAFFIC_REQUIRED=0
AUTOCAR_LANE_REQUIRED=0
AUTOCAR_LANE_BACKEND=opencv
```

這不影響 YOLO26 預覽模型，但會避免使用者誤開自動駕駛時因模型缺失而報錯。正式自動駕駛應恢復必要模型檢查。

### 12.3 外接 USB Webcam

先用 `Picamera2.global_camera_info()` 確認編號，然後設定，例如：

```ini
AUTOCAR_CAMERA_INDEX=1
AUTOCAR_CAMERA_ROTATE_180=0
```

修改後必須重啟服務：

```bash
sudo systemctl restart autocar.service
```

### 12.4 CSI 畫面上下顛倒

使用：

```ini
AUTOCAR_CAMERA_ROTATE_180=1
```

不需要旋轉時：

```ini
AUTOCAR_CAMERA_ROTATE_180=0
```

轉向是在 Picamera2 管線完成，YOLO 輸入與網頁畫面會一致。

---

## 13. 啟動與驗證服務

重新載入並啟動：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now autocar.service
```

查看狀態：

```bash
systemctl status autocar.service --no-pager
```

查看即時日誌：

```bash
sudo journalctl -u autocar.service -f
```

按 `Ctrl+C` 只會離開日誌，不會停止服務。

確認端口：

```bash
sudo ss -ltnp | grep ':8000'
```

從 Pi 本機測試首頁：

```bash
curl -I http://127.0.0.1:8000/
```

測試狀態 API：

```bash
curl http://127.0.0.1:8000/api/status
```

取得目前 IP：

```bash
hostname -I
```

Windows 開啟：

```text
http://192.168.0.160:8000
```

正常頁面應包含：

- 連線狀態
- 車體啟用開關
- 方向按鍵與 STOP
- YOLO26 即時辨識畫面
- 推論 FPS、物件數與辨識摘要
- 雲台控制
- 錄影控制
- 自動駕駛狀態

---

## 14. 手動控制驗收流程

車輪必須先架空。

1. 開啟 Web UI。
2. 確認右上角顯示「連線」。
3. 啟用車體控制，確認四輪同速前進。
4. 短按 F，確認四輪加速及 UI PWM 更新。
5. 短按 B，確認四輪減速；減至 0% 不倒車。
6. 短按 L/R，確認轉向設定逐步變化及左右輪差速。
7. 放開按鍵，確認維持速度與轉向設定。
8. 按 STOP，確認立即停止。
9. 關閉瀏覽器或中斷 Wi-Fi，確認 watchdog 約 0.8 秒後停止。
10. 若任何輪方向錯誤，先斷開馬達電源，再修改接線或方向映射。

鍵盤快捷鍵：

| 動作 | 鍵盤 |
|---|---|
| 加速 | `F`、`W` 或 ↑ |
| 減速 | `B`、`S` 或 ↓ |
| 逐步左轉 | `L`、`A` 或 ← |
| 逐步右轉 | `R`、`D` 或 → |
| 急停 | 空白鍵 |

---

## 15. 錄影與雲台驗證

### 15.1 錄影

在 Web UI 按「開始錄影」，完成後按「停止錄影」。檔案位於：

```bash
ls -lh /home/rpi5/Videos/autocar
```

### 15.2 雲台

先確認中心位置不會使機構卡死，再小角度測試上下左右。若方向相反，調整：

```ini
AUTOCAR_PAN_INVERT=1
AUTOCAR_TILT_INVERT=1
```

若中心不正，調整：

```ini
AUTOCAR_PAN_CENTER=0
AUTOCAR_TILT_CENTER=-80
```

每次只修改小幅度，避免伺服器撞擊機構限位。

---

## 16. 自訂交通與車道模型

大型訓練應在有 NVIDIA GPU 的 Windows/Linux 工作站或雲端進行，不建議在 Pi 5 訓練。

### 16.1 資料集結構

```text
dataset/
├── images/
│   ├── train/
│   └── val/
└── labels/
    ├── train/
    └── val/
```

交通模型建議類別名稱：

```text
red_light
yellow_light
green_light
stop_sign
```

車道分割類別：

```text
lane
```

### 16.2 執行訓練

在 GPU 工作站的專案根目錄：

```bash
python training/train_traffic.py
python training/train_lane.py
```

訓練前應修改：

- `training/traffic_light.yaml`
- `training/lane_seg.yaml`

使其中資料集路徑指向實際資料。

### 16.3 部署自訂模型

將完整 NCNN 目錄傳到 Pi，例如：

```powershell
scp -r "C:\path\to\traffic_best_ncnn_model" `
  rpi5@192.168.0.160:/home/rpi5/

scp -r "C:\path\to\lane_best_ncnn_model" `
  rpi5@192.168.0.160:/home/rpi5/
```

在 Pi 安裝：

```bash
sudo cp -a ~/traffic_best_ncnn_model /opt/autocar/models/
sudo cp -a ~/lane_best_ncnn_model /opt/autocar/models/
sudo chown -R rpi5:rpi5 /opt/autocar/models
sudo systemctl restart autocar.service
```

對應設定：

```ini
AUTOCAR_MODEL=models/traffic_best_ncnn_model
AUTOCAR_LANE_MODEL=models/lane_best_ncnn_model
AUTOCAR_LANE_BACKEND=auto
AUTOCAR_INFERENCE_IMGSZ=416
AUTOCAR_TRAFFIC_REQUIRED=1
AUTOCAR_LANE_REQUIRED=1
```

模型匯出尺寸必須與 `AUTOCAR_INFERENCE_IMGSZ` 相同。

---

## 17. systemd 常用操作

啟動：

```bash
sudo systemctl start autocar.service
```

停止：

```bash
sudo systemctl stop autocar.service
```

重新啟動：

```bash
sudo systemctl restart autocar.service
```

啟用開機啟動並立即啟動：

```bash
sudo systemctl enable --now autocar.service
```

停止並取消開機啟動：

```bash
sudo systemctl disable --now autocar.service
```

只取消下次開機啟動、不停止目前程序：

```bash
sudo systemctl disable autocar.service
```

查看最近 200 行日誌：

```bash
sudo journalctl -u autocar.service -n 200 --no-pager
```

查看本次開機完整日誌：

```bash
sudo journalctl -u autocar.service -b --no-pager
```

---

## 18. 更新專案

### 18.1 建立備份

```bash
sudo systemctl stop autocar.service

sudo cp -a /opt/autocar /opt/autocar.backup
sudo cp -a /etc/autocar.env /etc/autocar.env.backup
```

若備份目錄已存在，請改用不同名稱，例如：

```bash
sudo cp -a /opt/autocar /opt/autocar.backup-20260909
```

### 18.2 上傳並執行新版安裝

```bash
cd ~/RPI5_AutoCAR_integrated
sudo ./scripts/install_pi.sh
```

安裝後確認 `/etc/autocar.env` 是否需要加入新版設定欄位。

### 18.3 還原程式

先停止服務：

```bash
sudo systemctl stop autocar.service
```

將已確認的備份內容複製回正式目錄，再啟動：

```bash
sudo cp -a /opt/autocar.backup/. /opt/autocar/
sudo cp -a /etc/autocar.env.backup /etc/autocar.env
sudo systemctl start autocar.service
```

---

## 19. 效能調校

### 19.1 網頁視覺推論開關

影像卡片右上方的「視覺推論」開關控制 YOLO26 預覽模型：

- **關閉**：停止 YOLO26 NCNN 執行緒，網頁顯示不含偵測框的原始相機畫面；手控、雲台
  與 H.264 錄影不受影響，適合蒐集後續標記訓練用的素材。
- **開啟**：載入 YOLO26 NCNN，網頁顯示畫框、FPS、物件數及辨識類別。
- **啟動自動駕駛**：系統會自動開啟視覺推論。自動駕駛運行期間不能單獨關閉推論，
  必須先關閉自動駕駛。

後端 API：

```text
POST /api/detection/enable
Content-Type: application/json

{"enabled": true}
```

關閉時傳入 `false`。`GET /api/status` 的 `detection.enabled`、`running`、`fps`、`count`、
`labels` 與 `error` 可用於確認狀態。此開關只停止推論，不會關閉共享相機，因此切換時
不會中斷正在進行的 H.264 錄影。

### 19.2 建議起始值

```ini
AUTOCAR_PREVIEW_IMGSZ=640
AUTOCAR_PREVIEW_CONFIDENCE=0.40
AUTOCAR_PREVIEW_MAX_DET=20
AUTOCAR_PREVIEW_JPEG_QUALITY=65
```

### 19.3 降低串流負擔

依序調整：

1. 降低 JPEG quality，例如 `55`。
2. 降低最大偵測數，例如 `10`。
3. 使用真正以 416 匯出的 NCNN 模型。
4. 只開一個瀏覽器串流頁籤。
5. 關閉不必要的背景服務。
6. 確保主動散熱正常。

範例：

```ini
AUTOCAR_PREVIEW_MODEL=models/yolo26n_416_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=416
AUTOCAR_PREVIEW_MAX_DET=10
AUTOCAR_PREVIEW_JPEG_QUALITY=55
```

不能只改 `AUTOCAR_PREVIEW_IMGSZ`；模型本身也必須以相同尺寸匯出。

### 19.4 尺寸、速度與辨識率的取捨

以下是 Raspberry Pi 5 CPU + YOLO26n NCNN 的規劃參考值，不是效能保證；實際結果會受
散熱、時脈、記憶體、相機、JPEG 編碼、模型內容及同時連線數影響：

| NCNN 輸入尺寸 | 原始推論參考 | 網頁串流參考 | 使用建議 |
|---:|---:|---:|---|
| 640 × 640 | 約 12–15 FPS | 約 5–10 FPS | 辨識率優先；目前預設 |
| 416 × 416 | 約 18–28 FPS | 約 10–18 FPS | 速度與精度折衷 |
| 320 × 320 | 約 25–40 FPS | 約 15–25 FPS | Pi 5 建議先測的效能版 |
| 256 × 256 | 約 35–55 FPS | 約 18–30 FPS | 近距離、大目標情境 |
| 128 × 128 | 可能超過 60 FPS | 常受串流限制於 20–30 FPS | 僅適合實驗；小物件容易漏檢 |

本專案曾在 640 NCNN 單張測試觀察到約 `74–81 ms` 推論時間，約等於 12–13.5 FPS 的
純推論上限；加入相機擷取、畫框及 JPEG/MJPEG 傳輸後，網頁 FPS 一定會更低。

128 × 128 可以減少 CPU、記憶體及熱量負擔，但交通燈和遠方標誌在縮圖後可能只剩數個
像素，辨識率會大幅下降。因此建議測試順序為 `320 → 256 → 128`，以實際道路畫面確認
是否仍能穩定辨識，不應只追求 FPS。

### 19.5 可重複的 FPS 基準測試

先停止正式服務，避免兩份程式同時占用資源；測試可使用一張已存在的圖片，因此不需
占用相機：

```bash
sudo systemctl stop autocar.service

/opt/autocar-venv/bin/python - <<'PY'
from pathlib import Path
from statistics import mean
from time import perf_counter
from ultralytics import YOLO

model_path = "/opt/autocar/models/yolo26n_320_ncnn_model"
image_path = "/opt/autocar/test.jpg"
imgsz = 320
runs = 50

if not Path(image_path).is_file():
    raise SystemExit(f"測試圖片不存在: {image_path}")

model = YOLO(model_path)
for _ in range(5):
    model.predict(image_path, imgsz=imgsz, device="cpu", verbose=False)

times = []
for _ in range(runs):
    started = perf_counter()
    model.predict(image_path, imgsz=imgsz, device="cpu", verbose=False)
    times.append(perf_counter() - started)

average = mean(times)
print(f"平均完整 predict: {average * 1000:.1f} ms")
print(f"平均完整 predict FPS: {1 / average:.2f}")
PY

sudo systemctl start autocar.service
```

比較不同尺寸時，必須同步修改 `model_path` 與 `imgsz`。第一次執行包含載入與初始化，
所以範例先暖機 5 次，再統計 50 次。

### 19.6 降低尺寸能否解決當機

降低尺寸能減輕持續高負載、熱節流、記憶體壓力及部分供電壓力，但不是所有當機的修復
方式。以下問題必須分別解決：

- `No module named 'ncnn'`：把 `ncnn` 安裝到 `/opt/autocar-venv` 後重啟服務。
- `libtorch_cpu.so: undefined symbol: sbgemm_`：修復正式虛擬環境中的 NumPy／SciPy／CPU PyTorch。
- `Device or resource busy`：停止另一份相機或串流程式。
- 模型尺寸不匹配：重新匯出正確尺寸並同步修改兩個環境欄位。
- 電源、溫度或 OOM：檢查低電壓、散熱、記憶體及上次開機核心日誌。

發生整板重新啟動或失去回應時，先收集：

```bash
vcgencmd get_throttled
vcgencmd measure_temp
free -h
sudo journalctl -k -b -1 --no-pager | tail -n 200
sudo journalctl -u autocar.service -b -1 --no-pager | tail -n 200
```

如果日誌只顯示推論錯誤但系統仍可 SSH，通常是應用程式問題；如果 Pi 完全失聯、重新
開機或有低電壓紀錄，才優先處理供電與散熱。

### 19.7 避免重複推論

以下程式不要與整合服務同時執行：

```text
yolo_web_stream.py
camera_test.py
rpicam-hello
另一份 autocar.server
```

檢查 Python 程序：

```bash
ps -eo pid,%cpu,%mem,rss,etime,cmd | grep -E '[a]utocar|[y]olo|[p]ython'
```

檢查端口：

```bash
sudo ss -ltnp | grep -E ':8000|:8080'
```

正式整合版只需要 `:8000`。

---

## 20. 供電、溫度與記憶體監控

YOLO、相機與 JPEG 壓縮會長時間提高 CPU 負載。

另開一個 SSH 視窗：

```bash
watch -n 1 'vcgencmd measure_temp; vcgencmd get_throttled; free -h'
```

正常 `get_throttled`：

```text
throttled=0x0
```

重要值：

| 值／bit | 意義 |
|---|---|
| `0x1` | 目前低電壓 |
| `0x4` | 目前降頻 |
| `0x8` | 目前達軟性溫度限制 |
| `0x10000` | 開機後曾發生低電壓 |
| `0x20000` | 開機後曾限制 Arm 頻率 |
| `0x40000` | 開機後曾發生降頻 |
| `0x80000` | 開機後曾達軟性溫度限制 |

Pi 5 在 80–85°C 會逐步降頻。持續推論應使用 Active Cooler。

監控服務記憶體：

```bash
watch -n 2 'free -h; ps -C python -o pid,%cpu,%mem,rss,etime,cmd'
```

若 RSS 長時間持續增加，需調查記憶體累積。

重新開機後檢查上次核心錯誤：

```bash
journalctl -b -1 -k --no-pager | \
  grep -Ei 'under|voltage|thermal|thrott|oom|killed|segfault|bus error|mmc|i/o error|ext4|watchdog'
```

---

## 21. 常見問題排除

### 21.1 `No module named 'ultralytics'`

原因：用了系統 Python，而不是專案虛擬環境。

正式服務測試應使用：

```bash
/opt/autocar-venv/bin/python -c "import ultralytics; print(ultralytics.__version__)"
```

開發環境使用：

```bash
cd ~/autocar
source .venv/bin/activate
python -c "import ultralytics; print(ultralytics.__version__)"
```

### 21.2 pip 下載大量 NVIDIA CUDA 套件

Pi 5 不需要 NVIDIA CUDA。這次實際發生的原因是：

1. 已從 PyTorch CPU index 成功安裝 `torch-2.14.0+cpu`。
2. 隨後執行 `pip install --force-reinstall ultralytics ncnn`。
3. `--force-reinstall` 要求 pip 連相依套件一起重裝。
4. pip 從一般 PyPI 選到 `torch-2.14.0`，並開始下載 CUDA 13、cuDNN、cuBLAS、NCCL、
   Triton 等數 GB 套件。
5. 最後出現 `[Errno 28] No space left on device`。

立即停止下載。以下命令在 Pi 5 上是**禁止用法**：

```bash
sudo /opt/autocar-venv/bin/python -m pip install \
  --force-reinstall ultralytics ncnn
```

先停止服務，移除可能已安裝的 CUDA 套件：

```bash
sudo systemctl stop autocar.service

sudo /opt/autocar-venv/bin/python -m pip uninstall -y \
  cuda-toolkit cuda-bindings cuda-pathfinder \
  nvidia-cudnn-cu13 nvidia-cusparselt-cu13 \
  nvidia-nccl-cu13 nvidia-nvshmem-cu13 nvidia-cublas \
  nvidia-cuda-nvrtc nvidia-cuda-runtime nvidia-cufft \
  nvidia-nvjitlink nvidia-cufile nvidia-cuda-cupti \
  nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-nvtx \
  triton
```

顯示部分套件未安裝是正常的。接著清理快取與 apt 套件檔：

```bash
sudo /opt/autocar-venv/bin/python -m pip cache purge
python3 -m pip cache purge
sudo apt clean
df -h /
```

根目錄建議至少保留 2 GiB。重新確認或安裝 CPU wheel：

```bash
sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade --force-reinstall --no-cache-dir \
  torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu
```

CPU PyTorch 裝好後，修復 Ultralytics 時禁止它再次解析 PyTorch：

```bash
sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade --no-cache-dir --no-deps ultralytics

sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade --no-cache-dir ncnn
```

驗證：

```bash
/opt/autocar-venv/bin/python - <<'PY'
import torch
import torchvision

print("PyTorch:", torch.__version__)
print("Torchvision:", torchvision.__version__)
print("CUDA:", torch.cuda.is_available())
assert "+cpu" in torch.__version__, "目前不是 +cpu wheel"
assert not torch.cuda.is_available(), "Pi 5 不應使用 CUDA runtime"
print("CPU PyTorch: READY")
PY
```

完成後再執行第 21.4 節的完整 AI runtime 聯合載入測試。新版 `install_pi.sh` 會先檢查
根目錄空間，並以 `--upgrade-strategy only-if-needed` 安裝 Ultralytics/NCNN，保留已安裝的
CPU PyTorch。

### 21.3 NumPy sanity check failed

若 traceback 指向：

```text
/usr/lib/python3/dist-packages/numpy/
```

在相應虛擬環境安裝 NumPy/SciPy：

```bash
python -m pip install \
  --upgrade \
  --force-reinstall \
  --no-cache-dir \
  numpy scipy
```

確認：

```bash
python - <<'PY'
import numpy
print(numpy.__version__)
print(numpy.__file__)
PY
```

路徑應位於虛擬環境的 `site-packages`。

### 21.4 `libtorch_cpu.so: undefined symbol: sbgemm_`

這表示 `/opt/autocar-venv` 載入的 BLAS／NumPy 二進位介面與 PyTorch 不相容。常見現象
是原始相機畫面正常，但打開「視覺推論」後立刻顯示錯誤；因此它不是相機、NCNN 模型
檔案或網路串流故障。

新版後端會在切換畫框串流前，按照 `OpenCV → NumPy → PyTorch → Ultralytics → NCNN`
的順序聯合載入。NCNN 必須放在 PyTorch 之後；若先載入 NCNN，其原生運算函式庫可能
先占用 BLAS 符號，使後載入的 `libtorch_cpu.so` 找不到 `sbgemm_`。若預檢失敗，API
會拒絕開啟推論、網頁開關回復關閉，
並繼續提供原始畫面，讓手控、錄影與訓練素材取景仍可使用。

如果錯誤是在推論工作執行緒啟動後才發生，後端會把 `detection.enabled` 自動改為
`false`；網頁每秒取得狀態時會發現啟用狀態下降，自動重新連接同一個相機 URL。新連線
會改走原始 MJPEG，不再停留在黑色的失效畫框串流，但會保留錯誤文字供排查。

停止服務：

```bash
sudo systemctl stop autocar.service
```

強制重裝正式服務環境的 NumPy/SciPy 與 CPU PyTorch：

```bash
sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade \
  --force-reinstall \
  --no-cache-dir \
  numpy scipy

sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade \
  --force-reinstall \
  --no-cache-dir \
  torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu
```

聯合驗證；輸出的 NumPy 路徑應位於 `/opt/autocar-venv/lib/python3.13/site-packages`：

```bash
/opt/autocar-venv/bin/python - <<'PY'
import cv2
import numpy
import torch
import torchvision
import ultralytics
import ncnn

print("NumPy:", numpy.__version__, numpy.__file__)
print("OpenCV:", cv2.__version__)
print("PyTorch:", torch.__version__, torch.__file__)
print("Torchvision:", torchvision.__version__)
print("NCNN:", ncnn.__file__)
print("Ultralytics:", ultralytics.__version__)
print("AI runtime: READY")
PY
```

只有看到 `AI runtime: READY` 才重新啟動：

```bash
sudo systemctl start autocar.service
sudo journalctl -u autocar.service -n 100 --no-pager
```

新版 `install_pi.sh` 會在服務啟動前執行相同的聯合載入測試。第一次失敗會自動強制
重裝 NumPy／SciPy 與 CPU PyTorch 並再測一次；第二次仍失敗時，安裝腳本會以非零狀態
停止，不會啟動帶有損壞推論環境的服務。

#### 2026-09-10 實機排查紀錄

新版網頁提供「推論模型與固定尺寸」選單。使用順序為：停止自動駕駛、關閉視覺推論、
選擇 `模型名稱（尺寸×尺寸）`、按下「套用」、重新開啟視覺推論。後端只列出
`/opt/autocar/models` 中具有有效 `metadata.yaml` 的方形 NCNN 模型，並拒絕尺寸不符或
推論運行中的切換要求。執行期切換不修改 `/etc/autocar.env`；若需永久以 320 開機，請將
模型與 `AUTOCAR_PREVIEW_IMGSZ=320` 一起寫入環境檔後重啟服務。

本次進一步確認：單獨載入完整 AI runtime 正常，但服務在 Picamera2 已完成相機初始化後
才載入 PyTorch，會回傳 `undefined symbol: sbgemm_`。最終修正是在 HTTP server 開始服務
之前執行 `DETECTION.preload_runtime()`，固定由 PyTorch 先載入所需原生函式庫；這項修正
同時適用 320 與 640 模型。

本次依序完成以下測試：

1. `import torch` 成功，版本為 `2.14.0+cpu`、CUDA 為 `False`。
2. `OpenCV → NumPy → PyTorch` 成功。
3. 完整 AI runtime 與 `from ultralytics import YOLO` 成功。
4. `Picamera2 → OpenCV → NumPy → PyTorch → Ultralytics → NCNN` 成功。
5. `/opt/autocar/models/yolo26n_ncnn_model` 以 `imgsz=640` 單張推論成功。

最後發現 `/etc/autocar.env` 曾同時設定：

```ini
AUTOCAR_PREVIEW_MODEL=models/yolo26n_320_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=640
```

模型與執行尺寸不匹配。改成以下一致組合並重啟服務後，網頁推論成功：

```ini
AUTOCAR_PREVIEW_MODEL=models/yolo26n_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=640
```

因此看到 `sbgemm_` 時不可立刻假定 PyTorch 損壞。先依上述 1–5 項分層測試，再檢查
`AUTOCAR_PREVIEW_MODEL`、`AUTOCAR_PREVIEW_IMGSZ` 與該模型 `metadata.yaml` 是否一致。

### 21.5 `No module named 'ncnn'`

原因是 Ultralytics 第一次推論時才發現 NCNN runtime 缺失。服務帳號無法寫入
`/opt/autocar-venv`，自動更新會退回 `/home/rpi5/.local`；當次已運行的服務仍無法載入，
所以串流維持黑畫面。

將 NCNN 明確裝入正式服務環境：

```bash
sudo systemctl stop autocar.service

sudo /opt/autocar-venv/bin/python -m pip install \
  --upgrade \
  --no-cache-dir \
  ncnn

/opt/autocar-venv/bin/python -c "import ncnn; print('NCNN runtime: READY')"

sudo systemctl start autocar.service
```

不要依賴 Ultralytics 在 systemd 服務運行期間自動安裝依賴。新版 `install_pi.sh` 已將
`ncnn` 納入安裝及啟動前驗證。

### 21.6 `qt.qpa.xcb: could not connect to display`

原因：透過 SSH 執行 `cv2.imshow()`，但 SSH 沒有圖形桌面。

整合版使用網頁串流，不需 `cv2.imshow()`。開啟：

```text
http://<Pi-IP>:8000
```

### 21.7 `Device or resource busy`

停止其他相機程式：

```bash
sudo systemctl stop autocar.service
sudo fuser -v /dev/video* /dev/media*
```

確認沒有 `rpicam-hello`、`camera_test.py` 或獨立串流仍在執行。

### 21.8 網頁顯示黑畫面／推論錯誤

查看服務日誌：

```bash
sudo journalctl -u autocar.service -n 200 --no-pager
```

確認模型：

```bash
find /opt/autocar/models/yolo26n_ncnn_model -maxdepth 1 -type f -printf '%f\n'
```

確認設定：

```bash
grep -E '^AUTOCAR_(CAMERA|PREVIEW)' /etc/autocar.env
```

確認服務帳號可讀：

```bash
sudo -u rpi5 test -r /opt/autocar/models/yolo26n_ncnn_model/model.ncnn.param && echo param-OK
sudo -u rpi5 test -r /opt/autocar/models/yolo26n_ncnn_model/model.ncnn.bin && echo bin-OK
```

### 21.9 `Bus error`

依序確認：

1. NCNN 模型匯出尺寸與設定相同。
2. 單張 NCNN 推論正常。
3. NumPy、PyTorch 與 NCNN 都來自同一虛擬環境。
4. 沒有同時運行兩份推論服務。
5. 記憶體、溫度與供電正常。

單張測試：

```bash
cd ~/autocar
./.venv/bin/yolo predict \
  model=yolo26n_ncnn_model \
  source=bus.jpg \
  imgsz=640
```

### 21.10 `pip check` 顯示 Flask、tree-sitter 或 debconf 缺失

因虛擬環境使用 `--system-site-packages`，`pip check` 也可能檢查 apt 管理的型別提示套件。只要以下針對性驗證成功，就不要為了清空列表安裝與 AutoCAR 無關的 Flask/tree-sitter 套件：

```bash
/opt/autocar-venv/bin/python - <<'PY'
import numpy
import cv2
import torch
import torchvision
import ultralytics
from picamera2 import Picamera2

print("Environment: READY")
PY
```

### 21.11 端口 8000 被占用

```bash
sudo ss -ltnp | grep ':8000'
```

不要同時手動執行另一份 `python -m autocar.server`。正式環境由 systemd 管理。

---

## 22. 開發與測試

在 Windows 專案根目錄執行語法檢查：

```powershell
python -m compileall -q autocar scripts tests
```

執行測試：

```powershell
python -m unittest discover -s tests -v
```

目前測試涵蓋：

- 交通狀態多幀投票
- 紅燈／停止標誌即時安全狀態
- PID 輸出限制
- 預覽模型缺失時的錯誤處理

本機沒有 Picamera2/PCA9685 時，仍可驗證標準 HTTP 首頁與狀態 API；硬體影像及馬達測試必須在 Pi 上完成。

---

## 23. 最終驗收清單

### 系統

- [ ] Raspberry Pi OS 64-bit，`uname -m` 為 `aarch64`
- [ ] 官方或等規格 5V/5A 電源
- [ ] Active Cooler 正常運轉
- [ ] `vcgencmd get_throttled` 無低電壓紀錄

### 相機與模型

- [ ] Picamera2 能列出正確相機
- [ ] 模型目錄包含 YAML、PARAM、BIN
- [ ] NCNN 單張推論成功
- [ ] 模型匯出尺寸與 `AUTOCAR_PREVIEW_IMGSZ` 相同
- [ ] Web UI 可看到畫框影像
- [ ] 畫面方向正確

### 車體

- [ ] `i2cdetect -y 1` 看得到 `0x40`
- [ ] 車輪架空完成啟用前進、F/B 加減速、L/R 差速轉向測試
- [ ] STOP 正常
- [ ] 放開按鍵維持設定；STOP、切換視窗與失聯會停止
- [ ] 網路中斷後 watchdog 停車
- [ ] 馬達使用獨立供電且共地

### 服務

- [ ] `autocar.service` 為 active/running
- [ ] 端口 8000 正常監聽
- [ ] 重新開機後服務自動啟動
- [ ] 沒有第二份相機或 YOLO 程式
- [ ] 日誌沒有 `sbgemm_`、OOM、低電壓或相機占用錯誤

---

## 24. 最短部署命令摘要

以下假設 OS、相機與 I²C 已完成測試，且整合 ZIP 已上傳至 `/home/rpi5`：

```bash
mkdir -p ~/RPI5_AutoCAR_integrated
unzip -o ~/RPI5_AutoCAR-YOLO-integrated.zip -d ~/RPI5_AutoCAR_integrated

cd ~/RPI5_AutoCAR_integrated
chmod +x scripts/install_pi.sh
sudo ./scripts/install_pi.sh

sudo mkdir -p /opt/autocar/models
sudo cp -a ~/autocar/yolo26n_ncnn_model /opt/autocar/models/
sudo chown -R rpi5:rpi5 /opt/autocar/models

sudo nano /etc/autocar.env
sudo systemctl restart autocar.service
systemctl status autocar.service --no-pager
sudo journalctl -u autocar.service -f
```

Windows 瀏覽器：

```text
http://<Pi-IP>:8000
```

---

## 25. 維護原則

1. `/opt/autocar` 放正式程式，不在其中直接開發。
2. `/etc/autocar.env` 保存硬體及模型設定，更新前備份。
3. `/opt/autocar/models` 保存完整 NCNN 模型目錄。
4. 所有正式啟停均使用 `systemctl`。
5. 不在服務運行時另開相機測試程式。
6. 更新 PyTorch 時必須使用 CPU wheel repository。
7. 每次更換模型都先做單張推論，再啟動即時串流。
8. 每次改馬達設定都先架空車輪。
9. 發生整板當機時，先查供電、溫度、OOM 和上次開機核心日誌。
10. 開放給其他網段以前，必須額外加入驗證、TLS 與網路存取控制。


## 26. 2026-09-16 板端更新與驗證紀錄

### 26.1 目前板端與驗證結果

使用者確認新版「可以正常操作」。本次使用 `GET /api/status` 及靜態檔案讀取
交叉驗證，未為了驗收額外驅動車輪。

| 項目 | 本次結果 |
|---|---|
| RPi5 SSH | `rpi5@192.168.0.160` |
| Web UI | `http://192.168.0.160:8000` |
| 程式位置／服務 | 更新脚本以 `/opt/autocar`／`autocar.service` 為目標 |
| 馬達／雲台後端 | 狀態 API 回報 `pca9685` |
| 新版車控欄位 | `speed_percent`、`steering_degrees`、`speed_step`、`steering_step`、`steering_max`、`wheel_pwm` 均已出現 |
| 車體狀態 | 查詢時停用、速度 0%、角度 0°，A/B/C/D 輸出均為 0% |
| 推論執行期設定 | `models/yolo26n_320_ncnn_model`、320 × 320，推論正在執行，無回報錯誤 |
| 前端一致性 | 板端 `app.js`、`index.html`、`style.css` 與本機 SHA-256 一致 |
| 本機一致性 | 7 個更新檔與此次部署包的 `manifest.json` 一致 |
| 自動化測試 | 14 項 Python 測試與 Node 前端操作測試通過 |

機器可讀的查核時間、狀態快照與檔案雜湊保存在
[`BOARD_VALIDATION_20260916.json`](BOARD_VALIDATION_20260916.json)。FPS 僅為查詢當下數值，
不代表長時間效能保證。後端原始檔未透過 SSH 重新下載；此次以本機部署包雜湊及新版
API 行為交叉確認，未宣稱完成板端後端逐檔比對。

`deploy/autocar.env` 保留原有 640 設定範例。本次程式更新不覆蓋板端環境檔、模型或
Python 套件；API 的 320 執行期設定不等於已核實 `/etc/autocar.env` 內容。

### 26.2 最新手動控制規格

- 服務啟動仍為停用；開啟 UI 車體控制後，四輪以 `AUTOCAR_MANUAL_SPEED` 同速前進，預設 50% PWM。
- F／↑／W 每按一次加 5%；B／↓／S 每按一次減 5%；速度範圍 0–100%，B 不倒車。
- L／←／A 每按一次向左調 5°；R／→／D 每按一次向右調 5°；預設範圍 −45° 至 +45°。
- 相反轉向鍵逐步回正再轉往另一側；「轉向歸零」立即設為直行，維持轉速設定。
- 長按不重複累加，放開維持設定。STOP／空白鍵停止並歸零；F 可由 0% 再起步。
- 切換視窗、隱藏頁面送出 STOP；心跳中斷超過 watchdog 時限停車。

A/C 為左側、B/D 為右側；沿用參考程式 PCA9685 通道與 D 馬達 BCM25/24 方向接線。
同一控制週期更新四輪，取消左右兩側間的 10 ms 延遲，但 I²C 寫入仍依序進行。

轉向使用差速：外側 PWM 等於速度設定，內側 PWM 為
`速度設定 × (1 − 0.8 × |轉向設定| / 最大角度)`。最大轉向時內側保留 20% 輸出。
UI 顯示 PWM 比例與轉向設定刻度；無編碼器／車頭角度感測器，因此不是實測 RPM、
實際輪子轉角或一次按鍵實際轉過的車頭角度。

新增設定：

```ini
AUTOCAR_MANUAL_SPEED_STEP=5
AUTOCAR_MANUAL_STEERING_STEP=5
AUTOCAR_MANUAL_STEERING_MAX=45
```

瀏覽器每 200 ms 呼叫 `/api/vehicle/heartbeat`，不重送增量指令。
`/api/vehicle/drive` 的 `forward/backward/left/right` 已改為加速／減速／左調／右調，
`center` 用於回正，`stop` 用於停止。舊客戶端不可繼續每 300 ms 重送方向指令，
否則會重複累加。自動模式維持獨立的連續左右輪控制，手動心跳不延長自動模式 watchdog。

### 26.3 更新內容與備份

此次更新 7 個檔案：

```text
autocar/config.py
autocar/motor.py
autocar/autopilot.py
autocar/server.py
web/app.js
web/index.html
web/style.css
```

部署材料保存在 `deploy/rpi5-update/`：`update.sh`、`update.tar.gz`、
`update.sha256` 與 `manifest.json`。腳本先檢查服務目錄、驗證壓縮檔與執行 mock 測試，
再備份上述 7 檔、停止服務、覆寫檔案、啟動服務並驗證新版狀態 API。
更新後驗證失敗會還原備份並重啟。備份路徑格式為
`/opt/autocar-backup-YYYYMMDD-HHMMSS/`，以實際 `UPDATE_OK Backup:` 輸出為準；
本次未取得精確備份目錄名稱。

本次傳送方式是由 Windows `192.168.0.134:8765` 暫時提供更新包，再由已登入的板端下載。
這是當次傳送位置，不是永久下載站。下次要使用相同腳本，須確認電腦位址並重新啟動檔案服務：

```powershell
python scripts/package_release.py
python -m http.server 8765 --bind 192.168.0.134 --directory deploy/rpi5-update
```

在板端 SSH 終端執行：

```bash
curl -fsS http://192.168.0.134:8765/update.sh -o /tmp/autocar-update.sh
sudo bash /tmp/autocar-update.sh
```

若電腦 IP 改變，須同步調整 `update.sh` 的下載位址與上述指令。密碼在 SSH 終端輸入，
不放入專案或文件。已安裝板端的程式更新不必重跑 `install_pi.sh` 的套件安裝程序。

### 26.4 最新完整壓縮檔

`RPI5_AutoCAR-YOLO-integrated.zip` 已以最新本機程式及文件重新產生。
內容包含 `autocar/`、`web/`、`tests/`、`scripts/`、`deploy/`、`docs/`、`training/`、
README 與 requirements；排除模型、錄影、Git 資料、Python 快取與暫存簡報拆解內容。
`deploy/rpi5-update/` 的生成壓縮包與 manifest 由打包腳本重建，不重複放入完整 ZIP。
旁邊的 `.zip.sha256` 可檢查傳輸完整性。
