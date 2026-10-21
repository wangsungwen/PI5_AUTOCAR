# Raspberry Pi 5 AutoCAR 影片抽幀與訓練資料集製作備忘錄

本備忘錄記錄 `D:\ResearchCodes\RPI5_AutoCAR\video` 錄影檔案切割成圖片（1 秒 1 張 / 1 FPS）的實作過程、技術細節、自動化工具腳本與後續 YOLO 資料集標註建議。

---

## 1. 實作背景與目的

- **來源**：由 Raspberry Pi 5 搭載之 Pi Camera（Picamera2）於車體運行時錄製的實際賽道／場地影片。
- **目的**：將高解析度錄影畫面依固定時間週期（每秒 1 張）抽幀，去除冗餘時間影格，萃取為 YOLO 物件偵測（紅綠燈、停止標誌）及車道線分割（Lane Segmentation）模型訓練的標註素材（Annotation Dataset）。
- **挑戰**：Pi Camera 錄製產生的是原始 H.264 Elementary Stream（`.h264`），缺少一般 MP4 封裝容器的影格率標頭（Container Timing Metadata）。若直接交給通用轉換工具，解碼器通常會預設為 25 FPS，導致抽幀時間軸產生偏差。

---

## 2. 影片規格分析與幀率校準

### 2.1 原始錄影分析

透過 `ffprobe` 與影格計數深入檢驗 `video/` 目錄下的 3 部原始影片：

| 檔案名稱 | 檔案大小 | 總影格數 (`nb_read_frames`) | 推算實際長度 (以 30 FPS 計) | 抽幀結果 (1 FPS) |
| :--- | :---: | :---: | :---: | :---: |
| `autocar-20260915-192116.h264` | 44.3 MB (46,482,155 B) | **1,910 幀** | 約 63.66 秒 | **64 張** |
| `autocar-20260915-192627.h264` | 44.8 MB (47,059,194 B) | **1,883 幀** | 約 62.76 秒 | **63 張** |
| `autocar-20260915-193311.h264` | 45.3 MB (47,502,381 B) | **1,876 幀** | 約 62.53 秒 | **63 張** |
| **總計** | **約 134.4 MB** | **5,669 幀** | **約 189 秒（3 分 9 秒）** | **190 張** |

### 2.2 幀率偏差校準原理

檢視後端相機錄製實作 [`autocar/camera.py`](../autocar/camera.py)：
```python
self._camera.start_encoder(
    H264Encoder(bitrate=6_000_000), FileOutput(str(self._file)), name="main"
)
```
- Picamera2 `create_video_configuration` 於 1280×720 預設運作幀率為 **30 FPS**，碼率為 6 Mbps。
- 運算驗證：`1910 frames / 30 fps = 63.66 秒`；`46,482,155 Bytes / 63.66 s ≈ 730 KB/s ≈ 5.84 Mbps`，完全符合錄影參數。
- **校準解法**：在 FFmpeg 指令中，必須在 `-i` 前加上 `-r 30` 明確指定解碼輸入幀率，再掛載 `-vf fps=1`：
  ```bash
  ffmpeg -y -r 30 -i input.h264 -vf fps=1 -q:v 2 output/frame_%04d.jpg
  ```
  如此可確保每隔剛好 30 幀（真實時間每 1.0 秒）抽取 1 張畫面，避免解碼器以 25 FPS 誤判而抽取過多或時間失真的問題。

---

## 3. 自動化抽幀工具：`scripts/extract_frames.py`

為方便日後自走車上傳新錄影時可一鍵批次處理，已建立專用工具腳本 [`scripts/extract_frames.py`](../scripts/extract_frames.py)。

### 3.1 核心特性
1. **多格式支援**：支援 `.h264`, `.mp4`, `.mkv`, `.avi`, `.mov`, `.ts`。
2. **智慧幀率校正**：自動判斷副檔名，對 raw `.h264` 串流自動補上 `-r <input-fps>`（預設 30 FPS）。
3. **自訂抽幀頻率**：預設每秒 1 張（`--fps 1.0`），可自訂為任意小數或倍數（例如每秒 2 張 `--fps 2`，或每 2 秒 1 張 `--fps 0.5`）。
4. **高畫質輸出**：預設 JPEG 畫質參數 `-q:v 2`，保留 1280×720 原始解析度細節，利於遠處號誌標籤識別。
5. **批次與單檔雙模式**：可指定單一影片檔案，亦可自動遞迴掃描整個目錄。

### 3.2 使用指南

在專案根目錄開啟 PowerShell / Terminal：

```powershell
# 1. 預設處理：自動掃描 video/ 下所有影片，以 1 秒 1 張輸出至各影片專屬資料夾
python scripts/extract_frames.py

# 2. 指定單一影片並自訂每秒抽 2 張
python scripts/extract_frames.py --source video/autocar-20260915-192116.h264 --fps 2

# 3. 自訂輸出路徑
python scripts/extract_frames.py --source video --output my_dataset/raw_frames

# 4. 指定抽取為無損 PNG 格式
python scripts/extract_frames.py --format png
```

---

## 4. 本次成果目錄結構

```text
D:\ResearchCodes\RPI5_AutoCAR\
├── scripts\
│   └── extract_frames.py                     # [新增] 影片自動抽幀腳本
├── docs\
│   └── VIDEO_FRAME_EXTRACTION_MEMO_ZH_TW.md  # [新增] 本實作備忘錄
└── video\
    ├── autocar-20260915-192116.h264          # 原始錄影 1 (63.7s)
    ├── autocar-20260915-192116_frames\       # [產出] 64 張 JPG (frame_0001.jpg ~ frame_0064.jpg)
    ├── autocar-20260915-192627.h264          # 原始錄影 2 (62.8s)
    ├── autocar-20260915-192627_frames\       # [產出] 63 張 JPG (frame_0001.jpg ~ frame_0063.jpg)
    ├── autocar-20260915-193311.h264          # 原始錄影 3 (62.5s)
    └── autocar-20260915-193311_frames\       # [產出] 63 張 JPG (frame_0001.jpg ~ frame_0063.jpg)
```

- **單張圖片規格**：`1280 × 720`，色彩空間 YUV420 → JPEG，平均單張檔案大小約 120 KB ~ 140 KB。
- **總計產出**：190 張乾淨訓練樣本。

---

## 5. 後續資料集製作與訓練流程指引

抽幀完成後的 190 張圖片可接續以下標準 YOLO 訓練工作流：

### 5.1 資料篩選與清洗（Data Cleaning）
1. **剔除靜止無效影格**：自走車停在起點或終點等待時，多張連續畫面幾乎完全相同，建議手動剔除重複影像，避免模型對特定靜態背景過擬合。
2. **剔除運動模糊（Motion Blur）**：若車體急轉或顛簸造成嚴重模糊之影格，應予以過濾。

### 5.2 標註（Annotation）
可將圖片上傳至標註工具（如 [Roboflow](https://roboflow.com/)、[CVAT](https://www.cvat.ai/) 或本地 [LabelImg](https://github.com/HumanSignal/labelImg) / [AnyLabeling](https://github.com/vietanhdev/anylabeling)）：

- **物件偵測標註**（對應 [`training/traffic_light.yaml`](../training/traffic_light.yaml)）：
  - 類別 0: `red_light`（紅燈）
  - 類別 1: `yellow_light`（黃燈）
  - 類別 2: `green_light`（綠燈）
  - 類別 3: `stop_sign`（停止標誌）
- **車道遮罩分割**（對應 [`training/lane_seg.yaml`](../training/lane_seg.yaml)）：
  - 標註車道多邊形（Polygon Segmentation），作為語意分割訓練目標。

### 5.3 訓練與 NCNN 模型匯出
標註完成後，依序執行訓練並匯出至 Raspberry Pi 5 部署尺寸（建議 320×320 或 640×640）：
```bash
# 訓練 (以 YOLO26n 為例)
yolo detect train data=training/traffic_light.yaml model=yolo26n.pt epochs=100 imgsz=320 device=0

# 匯出至 NCNN 格式
yolo export model=runs/detect/train/weights/best.pt format=ncnn imgsz=320 batch=1 device=cpu
```
匯出後的 NCNN 目錄（含 `metadata.yaml`, `model.ncnn.param`, `model.ncnn.bin`）複製至 Pi 端的 `/opt/autocar/models/` 即可於網頁即時推論與自駕系統上線。
