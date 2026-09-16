# AutoCAR 自動駕駛延伸開發手冊

本延伸保留原有的 Web 手動遙控、H.264 錄影、MJPEG 預覽、雲台、PCA9685 四輪驅動與 watchdog。自動模式是可選模組；手動增量指令會先退出自動模式、停止，再套用手動設定；停用車體或服務停止都會關閉自動模式並停車。

## 執行架構

Picamera2 的同一個實例同時供預覽、錄影與 BGR 推論取幀使用。`lane-control` 執行緒以 YOLO26-seg 遮罩下半部質心估測車道中心，再由 anti-windup PID 輸出左右輪 PWM；`traffic-inference` 執行緒執行 YOLO26 Detect NCNN。紅燈或停止標誌單幀即停，解除停車以及綠／黃燈須通過預設 3/5 幀投票。車道信心不足、必要模型缺失或推論失敗時採 fail-safe 停車。

## Pi 5 安裝

先執行原有 `sudo ./scripts/install_pi.sh`，再安裝自動駕駛選配依賴：

```bash
sudo apt-get install -y python3-opencv python3-numpy
python3 -m venv ~/autocar-ai --system-site-packages
~/autocar-ai/bin/pip install -r requirements-autonomy.txt
```

安裝腳本會建立 `/opt/autocar-venv`，systemd 已設定使用該環境。將完整 NCNN 模型目錄部署為 `/opt/autocar/models/traffic_best_ncnn_model/` 與 `/opt/autocar/models/lane_best_ncnn_model/`。每個目錄應包含 `metadata.yaml`、`.param` 與 `.bin`。服務與手動控制在模型缺失時仍能啟動，但自動駕駛預設拒絕啟動。

Raspberry Pi 必須先從 PyTorch CPU index 安裝 `torch+cpu`。不可對 `ultralytics ncnn`
使用 `--force-reinstall`，否則 pip 可能改從一般 PyPI 下載 CUDA 版 torch 與數 GB 的
NVIDIA 套件，最後造成 `No space left on device`。修復 Ultralytics 時使用
`pip install --upgrade --no-cache-dir --no-deps ultralytics`，完整清理流程見部署備忘錄
第 21.2 節。

預覽 NCNN 是固定形狀模型。後端會讀取模型目錄的 `metadata.yaml`，並拒絕
`AUTOCAR_PREVIEW_MODEL` 與 `AUTOCAR_PREVIEW_IMGSZ` 不一致的組合。實機已驗證可用基準
為 `models/yolo26n_ncnn_model` 配 `640`；若使用 320 模型，設定也必須是 `320`。

### 執行期模型切換 API

`GET /api/status` 的 `detection.profiles` 會列出 `/opt/autocar/models` 內可用模型，並包含
`model`、`imgsz` 與顯示名稱。推論及自動駕駛皆關閉時，可呼叫：

```http
POST /api/detection/configure
Content-Type: application/json

{"model":"models/yolo26n_320_ncnn_model","imgsz":320}
```

後端只接受從模型 `metadata.yaml` 掃描出的配對，並再次驗證固定輸入尺寸。這是安全的
執行期設定，不寫入 `/etc/autocar.env`；服務重啟時恢復環境檔預設值。

服務的 `main()` 必須在建立 HTTP server、允許瀏覽器開啟 Picamera2 之前呼叫
`DETECTION.preload_runtime()`。Pi 5 實測若先完成相機初始化、稍後才載入 PyTorch，可能
因原生 BLAS 符號解析順序而出現 `libtorch_cpu.so: undefined symbol: sbgemm_`。

```bash
scp -r runs/detect/train/weights/best_ncnn_model rpi5@<Pi-IP>:/tmp/traffic_best_ncnn_model
scp -r runs/segment/train/weights/best_ncnn_model rpi5@<Pi-IP>:/tmp/lane_best_ncnn_model
ssh rpi5@<Pi-IP> 'sudo cp -a /tmp/traffic_best_ncnn_model /opt/autocar/models/ && sudo cp -a /tmp/lane_best_ncnn_model /opt/autocar/models/ && sudo chown -R rpi5:rpi5 /opt/autocar/models && sudo systemctl restart autocar'
```

## 資料集與訓練

交通號誌使用 YOLO Detect 邊界框；每個框應緊貼燈體，保留遠距離小目標並標記 `red_light`、`yellow_light`、`green_light`、`stop_sign`。車道使用 YOLO Seg 多邊形，沿可行駛車道區域標記。資料目錄均採 `images/train`、`images/val`、`labels/train`、`labels/val`。

在 GPU 主機安裝最新版 Ultralytics 後執行：

```bash
python training/train_traffic.py
python training/train_lane.py
```

訓練腳本採 Nano 預訓練權重、416 輸入並輸出 NCNN。交通類別名稱契約是 `red_light`、`yellow_light`、`green_light`、`stop_sign`；分割類別名稱預設為 `lane`。小目標建議增加遠距燈號樣本與縮放增強；若 416 的遠距辨識率不足，再針對資料與 Pi 5 實測提升至 512。

## 參數與安全策略

在 `/etc/autocar.env` 可設定：

```ini
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

`AUTOCAR_LANE_BACKEND=auto` 會在分割模型存在時使用 YOLO；只有設定 `AUTOCAR_LANE_REQUIRED=0` 時才允許退回 OpenCV。開發階段若只測手動功能，可暫時把兩個 `*_REQUIRED` 設為 `0`，實車自動模式建議維持 `1`。

實車第一次測試請架空車輪並使用低速。先將 KI/KD 設為 0 調 KP，加入 KD 抑制蛇行，最後只以極小 KI 修正長期偏差。依既有手動轉向邏輯，本驅動板採 A/C 為左側、B/D 為右側；若轉向成正回授，先核對實際接線，再調整左右映射或 steering 符號。反光誤判可提高閾值或縮小 ROI；高速時應提高前瞻範圍，不應單純提高 PID 增益。

## Web API

原 API 全部保留。新增 `POST /api/autopilot/enable`，JSON 為 `{ "enabled": true|false }`；`GET /api/status` 新增 `autopilot` 欄位，包含號誌、車道信心、PID 轉向、FPS 與錯誤。啟動後可直接在原控制頁的「自動駕駛」卡片操作。


## 2026-09-16 手動控制介面更新

`MotorController.drive()` 已改為增量速度及差速轉向控制，`backward` 現在是減速、不是倒車。
`set_enabled(True)` 會在停用轉為啟用時啟動手動定速前進；自動模式須使用
`set_enabled(True, start_manual=False)`，避免在模型開始控制前先行駛。

手動保活呼叫 `heartbeat()`；自動模式以 `drive_tank()` 更新命令時間，手動心跳不能
延長自動模式 watchdog。手動路由只在自駕啟用時呼叫 `AUTOPILOT.stop()`，避免每次
F/B/L/R 都清零累加狀態。狀態 API 新增速度、角度、步進上限與各輪 PWM；
UI 沒有將設定值標示為實測 RPM 或實測角度。

回歸驗證：

```bash
python -m unittest discover -s tests -v
node tests/test_manual_ui.js
```

本次板端與本機版本核對見 [部署備忘錄第 26 節](DEPLOYMENT_MEMO_ZH_TW.md#26-2026-09-16-板端更新與驗證紀錄)。
