# 2026-10-19 實機部署驗證

目標：`pi@192.168.0.160`，控制頁面：`http://192.168.0.160:8000`。

## 環境與部署

- Debian 13 / aarch64 / Python 3.13.5，約 4 GiB RAM；部署前根目錄可用約 14 GiB。
- 既有服務 `/opt/autocar`、環境 `/opt/autocar-venv`、設定 `/etc/autocar.env`；服務帳號 pi，已啟用開機啟動。
- 部署前比對 autocar Python 與 web 檔案，與 Windows RoadTrain 來源 SHA256 全部一致，保留既有套件環境。
- 備份：`/home/pi/deployment-20261019/autocar-before.tar.gz`，另有 `/etc/autocar.env.backup-*`。
- 原預覽路徑 `models/yolo26n_ncnn_model` 不存在，改為已安裝的 `models/lane_best_ncnn_model`，640×640。
- 保留實機已正確設定的 `AUTOCAR_LANE_CLASS=road` 與推論尺寸 640；手動初速調整為 25%。
- 系統環境的 pip check 有既有 Debian / 型別 stub 依賴警告，不能宣稱整個 system-site-packages 無衝突；實際 AI 與相機匯入及推論正常。

## 已驗證

- OV5647 相機可列舉、實際 JPEG 串流可取得；預覽影像 640×360。
- I²C bus 1 的 PCA9685 0x40 可讀取；馬達與雲台使用真實 pca9685 後端。
- 使用者確認車輪架空並備妥斷電後，執行短暫 25% 前進輸出；停止心跳後 1.3 秒檢查四輪 PWM 全為 0。這是停車結果檢查，非精密 watchdog 延遲量測。
- Pan/Tilt 各 5° 往返並恢復原位；使用者現場確認車輪、雲台有動作且車輪已停止。
- 道路 NCNN 640 即時狀態約 7.7 FPS；號誌 NCNN 640 約 9.8 FPS。這是短時狀態讀值，非長時間效能保證。
- 兩個 AirSim .pt 模型可在實機既有 runtime 載入並處理實拍影像，類別符合 road 與四種號誌標籤。
- Windows 與 Pi 的 RoadTrain 26 項測試通過（包含新增錄影停止回歸測試）。
- 測試期間讀取的 throttled 為 0x0；部分溫度取樣約 43～51°C，並非全程峰值。

## 發現並修正的錄影問題

Picamera2 的 `stop_encoder` 接受 Encoder 物件；原程式傳入 `"main"` / `"lores"` 字串，API 回報停止後 H.264 仍持續寫入。

已在 `autocar/camera.py` 保存 H264 Encoder 物件，停止錄影及關閉預覽時傳入各自物件。更新 Windows 來源與 Pi 正式程式，保留 `camera-before.py`。

修正後的實機測試：錄影約 3 秒，停止時 2,161,766 bytes；再等 3 秒仍相同，預覽仍可取得 JPEG。ffprobe 解出 83 幀、1280×720。裸 H.264 的標稱幀率不能用來代替實測錄影時間。

第一次 `hardware-validation.json` 的錄影結果只確認建立檔案，後續發現仍在寫入；錄影驗收以 `recording-fixed-validation.json` 和 `recording-fixed-ffprobe.json` 為準。

## 驗證範圍

相機目前拍到桌面，未提供道路或號誌真值標註；零偵測不代表模型精度通過或失敗。本次不啟用自動駕駛，不宣稱封閉道路行駛、道路 IoU、號誌召回率或閉迴路控制通過。

原始紀錄存放於 Pi `/home/pi/deployment-20261019` 與 Windows `C:\Users\TTU_SE\Documents\ChatGPT\RPI5_AutoCAR\deployment-20261019`。
