# 紅黃綠燈辨識模型：資料到 Raspberry Pi 5

本流程使用 YOLO26n 物件偵測，輸出燈號位置與 red_light、yellow_light、green_light 三類。現有 autocar/perception.py 可直接讀取這些類別。尚未準備真實資料，故目前交付的是訓練流程，不是訓練完成的權重。

## 1. 收集與標記

使用車上相機拍攝實際場景，涵蓋近遠距離、不同角度、室內外、逆光、反光及夜間。可先以每類數百個標記實例作為起點，依驗證結果補足資料；張數不保證準確率。黃燈時間較短，需特別收集。

使用 CVAT、Label Studio 或既有標記工具，匯出 YOLO detection 格式。每個框固定框住單一方向的整組燈具，依當下亮燈顏色分類；同一資料集不要混用整組燈具框與單顆燈泡框。無亮燈或無法判斷的樣本先排除；無交通燈的背景、車尾燈、招牌等可作負樣本，搭配空白 txt。多個燈具必須逐一標記。

類別順序必須為 0=red_light、1=yellow_light、2=green_light。
每行格式：`class_id x_center y_center width height`，座標除以影像寬高正規化至 0–1，例如：

```text
0 0.50 0.30 0.10 0.20
```

先按拍攝場次／影片分組，再分配 train/val/test（例如 70/20/10），避免同段影片相鄰影格跨集合。檢查器只會發現位元組相同的影像，不能代替場次分組。

```text
datasets/traffic/
  images/train/*.jpg
  images/val/*.jpg
  images/test/*.jpg
  labels/train/*.txt
  labels/val/*.txt
  labels/test/*.txt
```

影像與標記檔同名，也支援各集合下的同構子目錄。每個集合需包含所有宣告類別。test 備妥後，取消 training/traffic_lights_only.yaml 的 test 註解。沒有 test 時，只報告驗證集結果，不能當成獨立測試成績。

## 2. 安裝訓練環境

以下於專案根目錄的 PowerShell 執行，建議建立獨立 Python 3.11 環境（需先有該版本）：

```powershell
py -3.11 -m venv .venv-traffic
.\.venv-traffic\Scripts\python.exe -m pip install -r training/requirements-traffic.txt
```

若使用 NVIDIA GPU，先依 PyTorch 官方安裝頁安裝相容的 CUDA 版 PyTorch。CPU 可執行但訓練較慢。首次訓練會下載 yolo26n.pt 預訓練權重；它只是起始權重，不是已會區分三種燈色的模型。

## 3. 檢查與訓練

```powershell
.\.venv-traffic\Scripts\python.exe training/train_traffic.py --check-only
.\.venv-traffic\Scripts\python.exe training/train_traffic.py --device 0 --epochs 60 --batch 8 --name lights_v1
```

無 NVIDIA GPU 將 `--device 0` 改成 `--device cpu`。顯示記憶體不足可減小 batch。每次使用新的 name，避免覆蓋既有實驗。預設輸入為 416，若遠處燈號太小可比較 `--imgsz 640`；Pi 推論設定須同步修改。

檢查器確認影像可解碼、標記存在、類別順序、框範圍、孤立標記及重複影像，並統計各類實例與負樣本。空白 txt 是明確的負樣本；缺失 txt 視為錯誤。自訂 YAML 的相對 path 以 YAML 所在目錄解析，train/val/test 為資料根目錄下的 images 子目錄，不支援檔案清單或自動下載指令。

訓練停用色相變換、BGR 通道互換與翻轉，保留適量亮度／飽和度變化；仍須目視抽查增強結果是否可辨識。舊四類資料可指定 `--data training/traffic_light.yaml`，但必須有 stop_sign 樣本。

輸出位於 runs/traffic/lights_v1：

- dataset.resolved.yaml、dataset_summary.json：實際路徑與資料統計。
- weights/best.pt：驗證表現最佳的權重。
- evaluation.json、evaluation/：最佳權重的評估與圖表。
- weights/best_ncnn_model/：NCNN 匯出目錄，以程式實際印出的路徑為準。

保留訓練環境版本：

```powershell
.\.venv-traffic\Scripts\python.exe -m pip freeze > runs/traffic/lights_v1/environment.txt
```

## 4. 影片測試與匯出

```powershell
.\.venv-traffic\Scripts\yolo.exe predict model=runs/traffic/lights_v1/weights/best.pt source=你的測試影片.mp4 imgsz=416 conf=0.45 save=True
```

檢查每類 precision、recall、混淆矩陣及誤判影片，特別注意紅燈漏判與反光誤判，不只看整體 mAP。由獨立拍攝的測試集評估，並在實際 Pi 測量推論延遲；本流程不預設準確率或 FPS。

若 PC 的 NCNN 匯出環境不相容，可訓練時加 `--export none`，把 best.pt 複製到已安裝專案 AI 環境的 Pi，再執行：

```bash
yolo export model=best.pt format=ncnn imgsz=416 batch=1 device=cpu
```

匯出後亦可用 `yolo val model=best_ncnn_model data=資料設定.yaml imgsz=416 device=cpu` 在有資料集的機器比對匯出模型表現；資料設定需使用該機器有效路徑。

## 5. 接入現有 AutoCAR

將整個 best_ncnn_model 目錄（包括 metadata.yaml、param、bin）放入 Pi 的 `/opt/autocar/models/traffic_best_ncnn_model/`。在 `/etc/autocar.env` 設定：

```text
AUTOCAR_MODEL=/opt/autocar/models/traffic_best_ncnn_model
AUTOCAR_INFERENCE_IMGSZ=416
AUTOCAR_TRAFFIC_CONFIDENCE=0.45
```

若網頁預覽也要顯示三種燈號框，再設定：

```text
AUTOCAR_PREVIEW_MODEL=/opt/autocar/models/traffic_best_ncnn_model
AUTOCAR_PREVIEW_IMGSZ=416
```

在 Pi 執行 `sudo systemctl restart autocar`。先用預覽確認燈色與框位置，再在架高車輪或封閉測試場地驗證控制。這次只建立訓練流程，未變更車輛控制邏輯或板端服務；三類模型不提供停止標誌辨識。

## 官方參考

- [Ultralytics 訓練參數](https://docs.ultralytics.com/modes/train/)
- [NCNN 匯出](https://docs.ultralytics.com/integrations/ncnn/)
- [PyTorch 安裝](https://pytorch.org/get-started/locally/)
