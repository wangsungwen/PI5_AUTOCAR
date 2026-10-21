# 道路分割實作課程：影片取樣、Roboflow 標記與 YOLO26 反光改善

版本：2026-10-04。對象：已有道路實景影片、希望訓練道路分割模型的學員。主要操作環境為 Windows PowerShell；模型訓練可移到具 NVIDIA GPU 的 Linux 電腦。本課程交付 Markdown 教材與五支 Python 程式，原始碼位於 [training/road_reflection](../training/road_reflection/)。

本課程的 `road` 表示**可見的道路表面**，不是白線、黃線，也不表示道路一定可安全通行。水坑、障礙物與行車安全需要另外判斷。YOLO26 `-seg` 是實例分割；本課程把同類道路實例合併成道路遮罩，用於額外的像素評估。[模型說明](https://docs.ultralytics.com/zh/models/yolo26)

## 1. 課程目標與安排

完成後，學員應能從多段影片產生影像資料集、沿路面邊界標記多邊形、避免資料洩漏，並用對照實驗判斷反光增強是否有效。

| 單元 | 建議操作時間 | 交付物／完成條件 |
|---|---:|---|
| 影片盤點與抽幀 | 40 分鐘 | videos.csv、抽出的 JPG、frames.csv |
| Roboflow 分割標記 | 90 分鐘以上 | road 多邊形與人工複核紀錄 |
| 資料匯出與檢查 | 30 分鐘 | 通過檢查的 data.yaml 與三個集合 |
| 基準訓練 | 30 分鐘操作＋訓練等待 | best.pt、results.csv、args.yaml |
| 反光增強與對照 | 60 分鐘操作＋訓練等待 | 比較圖、各實驗權重 |
| 分場景評估與匯出 | 50 分鐘 | 評估 JSON、報告、匯出模型 |

時間為教學安排，不是模型訓練速度承諾。入門先以 300～600 張多樣畫面完成整條流程，再擴充；圖片數不是品質保證。

## 2. 已有多段影片：先分組，再轉圖片

### 2.1 建議抽幀密度

| 影片內容 | 起始取樣間隔 | 原因 |
|---|---:|---|
| 一般直路、緩速行駛 | 每 1～2 秒一張 | 減少相鄰重複畫面 |
| 快速彎道、陰影切換、短暫強光 | 每 0.2～0.5 秒一張 | 保留短暫失敗情境 |
| 長時間停車 | 每 5～10 秒一張或人工選取 | 避免靜止場景主導資料 |

10 分鐘影片以每 2 秒一張取樣，約產生 300 張。不要直接把 30 FPS 的每一幀都拿去標記；多拍不同路段、時間、天候，通常比相同場景大量重複更有價值。

將同一天同一路段、同一趟連續行駛的影片視為同一個 `session`。即使相機自動分成多個檔案，也不能分到不同集合。若目標是泛化到新路段，應把同一路段的不同場次也併為同一分組。以分組為單位，約 70%／20%／10% 分配到 train／valid／test，比例可以因資料量調整。每個集合都應有白天、夜間、雨天與反光場景；如果場次不足，先補拍，不要用相鄰影格湊測試集。

### 2.2 安裝 FFmpeg

在 PowerShell 執行以下安裝命令，完成後重新開啟 PowerShell：

```powershell
winget install "FFmpeg (Essentials Build)"
ffmpeg -version
ffprobe -version
```

若電腦沒有 winget，可從 [Windows FFmpeg builds](https://www.gyan.dev/ffmpeg/builds/) 下載 essentials ZIP，解壓縮後把 `bin` 加入 PATH。Linux 可使用 `sudo apt install ffmpeg`。

### 2.3 先試一段影片

在專案根目錄操作。下列 `videos/day01.mp4` 為自行替換的影片路徑：

```powershell
New-Item -ItemType Directory -Force datasets/preview_day01
ffmpeg -hide_banner -n -i videos/day01.mp4 -vf "fps=1/2" -q:v 2 datasets/preview_day01/day01_%06d.jpg
```

`fps=1/2` 是每 2 秒一張；每秒一張改為 `fps=1`，每秒兩張改為 `fps=2`。`-q:v 2` 指 JPEG 品質，數值不是百分比；`-n` 拒絕覆寫既有圖片。初次不縮放，保留原始細節。這些是 PowerShell 命令；若改寫成 `.bat`，檔名格式的 `%` 要寫成 `%%`。

只抽取 02:10 開始的 20 秒強反光片段：

```powershell
New-Item -ItemType Directory -Force datasets/preview_glare
ffmpeg -hide_banner -n -ss 00:02:10 -i videos/day01.mp4 -t 20 -vf "fps=2" -q:v 2 datasets/preview_glare/day01_glare_%06d.jpg
```

這些額外抽出的畫面必須跟原影片放在同一集合；不能拿去當新的獨立測試集。`fps` 依時間戳取樣，可能丟棄或重複來源幀，不應把輸出張數當成獨立場景數。[FFmpeg 濾鏡文件](https://ffmpeg.org/ffmpeg-filters.html#fps)

若使用專案的裸 `.h264` 錄影，先確認實際錄製 FPS；無可靠時間戳時，不能假設秒數正確。已確認是 30 FPS 才使用以下封裝範例：

```powershell
ffmpeg -n -fflags +genpts -r 30 -i videos/capture.h264 -c:v copy videos/capture.mp4
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 videos/capture.mp4
```

比較影片長度與錄影紀錄，再抽圖；錯誤的來源 FPS 會讓取樣時間偏移。

### 2.4 多段影片批次轉圖

在 `videos` 資料夾新增 `videos.csv`，UTF-8 格式。影片路徑相對於 CSV 所在資料夾：

```csv
video,clip_id,session,split,scene
day01.mp4,day01,routeA_trip01,train,day_normal
day02.mp4,day02,routeA_trip01,train,day_glare
rain01.mp4,rain01,routeB_trip02,valid,rain_glare
night01.mp4,night01,routeC_trip03,test,night_glare
```

這是格式示例，並未涵蓋每個集合所需的全部天候。請依實際影片新增更多獨立場次。`clip_id` 只能用英文字母、數字、底線、連字號，且不能重複。`scene` 是影像場景註記，不是模型的物件類別；若一段影片含多種天候／亮度，抽幀後再逐張修正 `frames.csv`。

```powershell
python training/road_reflection/extract_frames.py --manifest videos/videos.csv --output datasets/frames_v1 --interval 2
```

程式會逐段呼叫 FFmpeg，產生：

```text
datasets/frames_v1/
  train/day01_000001.jpg
  train/day02_000001.jpg
  valid/rain01_000001.jpg
  test/night01_000001.jpg
  frames.csv
```

程式會拒絕把同一 `session` 分到不同集合，也拒絕覆寫既有輸出。想快速試跑可加 `--max-per-video 20`；此選項只保留影片**開頭**的取樣，正式資料集通常不加，以免漏掉後段情境。失敗中斷後請檢查錯誤，再改用新的輸出資料夾重跑。

### 2.5 篩圖原則

保留真實的反光、雨夜、弱邊界、陰影與車燈情境，包括模型容易誤判的亮區。去除鏡頭完全被遮住、檔案損壞、無法判斷標記的全黑／全白畫面。輕微模糊若符合部署情境可保留，不要把所有困難樣本刪光。人工移除停車時幾乎相同的連續圖片。

抽幀後先檢查影像朝向。若相機實際輸入會旋轉 180°，資料也應採相同方向；需要旋轉時應在標記前完成，不能標記後只旋轉圖片。取景畫面不要帶偵測框、時間水印或控制介面。**JPEG 是未標記素材，還不能直接當 YOLO 分割訓練資料。**

## 3. Roboflow 道路多邊形標記

1. 登入 [Roboflow](https://roboflow.com/)，建立 Workspace 與專案，Project Type 選 **Instance Segmentation**。
2. 分別上傳 train／valid／test 影像，指定其集合；不要讓平台重新隨機分配影像而破壞場次分組。介面名稱可能變動，匯出後仍須核對集合與檔名。
3. 建立唯一類別 `road`。以 Polygon 沿可見道路外緣標記；可使用 SAM 標記助手產生初稿，再人工修正亮斑、陰影、路肩處。
4. 每張複核：不要把人行道、車身、天空或牆面反光標成 road。路面上的白線與可辨識的反光通常仍屬道路表面，不要沿亮斑形狀切割道路。
5. 遮擋的路面不憑空補畫。無法可靠判定的整張畫面先移到待複核區；本課程沒有實作「忽略區域」標籤。
6. 沒有道路的負樣本，在確認內容後標為無物件，匯出時以空 `.txt` 表示。缺失標籤不能直接視為負樣本。

平台支援多邊形標記與 SAM 輔助，匯出版本提供 YOLO 格式。[Roboflow 整合文件](https://docs.ultralytics.com/zh/integrations/roboflow)

本課程標記的是可見路面，不是「可行駛空間」規劃。若需要排除積水、深坑或障礙物，要先另訂類別與標記規範。多邊形若有孔洞或被障礙物切成多塊，應檢查匯出結果；YOLO 一列多邊形不能直接表示任意孔洞，必要時拆成多個可見區塊，再在像素評估時合併。

**檢核點：** 每位學員交 10 張複核範例，至少包含正常、強光、雨天、夜間；由另一人確認標記規則一致。

## 4. 前處理、版本與 Roboflow 增強

先建立 `v1_raw`：固定分組、標記完成、**不加隨機增強**，供基準與本地增強共用。可啟用 Auto-Orient；優先保留原尺寸，由 YOLO 訓練管線處理縮放與補邊。若教室要求固定 640×640，選保留比例的補邊方式，避免強制拉伸；檢查標記是否同步轉換，並確保所有對照版本一致。

另建 `v2_rf_light`，只對 train 加入下列候選設定：

| 項目 | 起始設定 | 解釋與檢查 |
|---|---|---|
| Brightness | −25%～+25% | 全圖明暗；不可讓大量邊界消失 |
| Contrast | −20%～+20% | 若介面沒有獨立項目，改用本地增強 |
| Grayscale | 約 10%～15% | 降低顏色依賴；不代表能恢復紋理 |
| Exposure | −10%～+10% | 全圖曝光變化，不是局部反光模擬 |

以上是**待驗證的課程起始值**，不是官方保證最佳設定。平台可用項目與幅度控制依當前介面為準；若沒有機率欄位，不要把「強度」當成「比例」。先用約 2 倍資料量，人工檢查產物，不要立即疊加所有效果。valid 與 test 保持真實影像，僅共用必要且固定的前處理。[Roboflow 增強文件](https://docs.roboflow.com/datasets/versions/dataset-versions/image-augmentation)

選 Generate 建立版本，再 Export Dataset。選可輸出**多邊形座標**的 YOLO26 格式；如果介面只列 YOLOv8 分割格式，也須確認匯出的是以下多邊形 TXT，而非偵測框或彩色遮罩 PNG。

## 5. 建立 Python 訓練環境

以下從專案根目錄執行；建議另建 Python 3.10 或 3.11 環境。Windows 若只裝 3.11，把第一行版本改成 `-3.11`。Pi 用於推論，完整訓練先在電腦完成。

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r training/road_reflection/requirements.txt
```

以下指令簡寫成 `python`／`yolo` 前，需啟用環境：

```powershell
.\.venv\Scripts\Activate.ps1
python -c "import torch, ultralytics, albumentations; print(torch.__version__, ultralytics.__version__, albumentations.__version__); print('CUDA:', torch.cuda.is_available())"
```

若啟用腳本被政策限制，可以一直用 `.\.venv\Scripts\python.exe` 與 `.\.venv\Scripts\yolo.exe`，不必改全機執行政策。`CUDA: False` 時先用 `--device cpu` 跑通流程；若已具 NVIDIA GPU，依 [PyTorch 安裝選擇器](https://pytorch.org/get-started/locally/) 安裝與平台相容的版本，再確認 CUDA。不要直接假設 `device=0` 在任何電腦都可用。

本課程將 Albumentations 固定為 2.0.8，以對應範例參數；Ultralytics 使用版本範圍，第一次成功安裝後記錄確切版本，所有實驗共用同一環境：

```powershell
python -m pip freeze > training/road_reflection/environment-lock.txt
```

這是當次環境紀錄，不是跨作業系統通用的 CUDA 安裝檔。Ultralytics 若偵測到 Albumentations，可能啟用自己的預設轉換，因此基準實驗也必須使用相同套件環境，並保存訓練啟動紀錄。[資料前處理說明](https://docs.ultralytics.com/guides/preprocessing-annotated-data)

## 6. 匯出資料檢查與 data.yaml

解壓縮 `v1_raw` 到 `datasets/road_export`，確認結構：

```text
datasets/road_export/
  data.yaml
  train/images/    train/labels/
  valid/images/    valid/labels/
  test/images/     test/labels/
```

每張 `xxx.jpg` 對應 `xxx.txt`。每列是一個物件，例如：

```text
0 0.10 0.95 0.40 0.40 0.60 0.40 0.90 0.95
```

第一個數字是類別 ID，後面是 0～1 的 `x1 y1 x2 y2 ...` 正規化座標；至少三點。偵測框的 `class x_center y_center width height` 五欄資料不能拿來訓練分割。[分割資料格式](https://docs.ultralytics.com/datasets/segment/)

```powershell
python training/road_reflection/prepare.py --source datasets/road_export --output datasets/road_base
```

程式要求恰好一個 `road` 類別，檢查空集合、缺失標籤、座標範圍、退化多邊形、同名圖片與跨集合完全相同檔案，然後複製到新資料夾並建立絕對路徑 YAML。它不能識別所有自交多邊形或近似影格，這些仍靠標記複核與場次分組處理。若匯出資料夾叫 `val`，先在匯出副本改名為 `valid`；來源原檔請保留。

產生的 YAML 大致如下，`path` 由程式自動寫入本機位置：

```yaml
path: C:/your-project/datasets/road_base
train: train/images
val: valid/images
test: test/images
names:
  0: road
```

此時只讀 train／valid 做開發；test 留到最終方案決定後再評估。搬到另一台電腦後，重新執行準備程式或更新絕對 `path`。

## 7. 第一個 YOLO26 基準模型

先用一輪、小批次確認路徑、標記與記憶體正常：

```powershell
python training/road_reflection/train.py --data datasets/road_base/data.yaml --profile baseline --name smoke --epochs 1 --batch 2 --device cpu
```

成功後用 GPU 正式訓練；沒有 GPU 則把 `--device 0` 改為 `--device cpu`，並接受較長等待時間：

```powershell
python training/road_reflection/train.py --data datasets/road_base/data.yaml --profile baseline --name A_base --epochs 50 --batch 8 --device 0
```

核心程式概念：

```python
from ultralytics import YOLO

if __name__ == "__main__":
    model = YOLO("yolo26n-seg.pt")
    model.train(
        data="datasets/road_base/data.yaml",
        epochs=50, imgsz=640, batch=8, device=0, workers=0,
        project="runs/road", name="manual_demo",
        hsv_h=0.0, hsv_s=0.3, hsv_v=0.2,
        scale=0.2, perspective=0.0, mosaic=0.0,
    )
```

完整腳本額外固定 optimizer、seed 與其他幾何增強，避免對照條件漂移。Windows 保留 `if __name__ == "__main__"` 與 `workers=0`。第一次載入模型會下載權重，需要網路。

檢查 `runs/road/A_base/` 的 `results.csv`、`results.png`、`args.yaml`、標籤／預測圖與 `weights/best.pt`。`best.pt` 依驗證表現選出；`last.pt` 是最後一輪，不一定最好。基準是保守增強，不是完全無增強。

## 8. 反光增強：分開比較，不一次全部加滿

原建議的 `hsv_v=0.4`、`hsv_s=0.7`、`scale=0.5`、`mosaic=1.0` 為常見預設值，不能稱為「已提高」。`perspective=0.001` 位於文件建議區間上限，對固定車載視角未必算輕微。Mosaic 拼接也可能破壞道路的連續幾何。本課程先採較保守的候選設定，再以驗證結果決定。[參數定義](https://docs.ultralytics.com/usage/cfg)

### 8.1 實驗 B：只改 YOLO 訓練增強

```powershell
python training/road_reflection/train.py --data datasets/road_base/data.yaml --profile reflection --name B_yolo --epochs 50 --batch 8 --device 0
```

`reflection` 為 `hsv_s=0.5, hsv_v=0.3, scale=0.3, perspective=0.0002, mosaic=0.2`。`close_mosaic=10` 讓末段關閉 Mosaic；其餘顏色等增強仍保留。若邊界連續性變差，下一輪只把 Mosaic 改為 0，其他條件維持固定。[YOLO 增強說明](https://docs.ultralytics.com/guides/yolo-data-augmentation)

### 8.2 實驗 C：本地 Albumentations 增強

```powershell
python training/road_reflection/augment.py --source datasets/road_base --output datasets/road_aug --fraction 0.5 --seed 42
```

從原始 train 選 50% 的圖片，各新增一張候選圖，所以 train 約為原來的 1.5 倍；不是每張都套上反光。原始 train 保留，valid／test 原樣複製。`augmentation.json` 記錄來源、種子及 Albumentations 版本。相同版本、檔案排序、種子可重建相同管線；跨套件版本不保證位元一致。

程式的核心增強如下；完整版本依影像尺寸調整耀斑半徑：

```python
import albumentations as A

transform = A.Compose([
    A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.15, p=0.5),
    A.RandomGamma(gamma_limit=(90, 110), p=0.2),
    A.ToGray(p=0.12),
    A.RandomSunFlare(flare_roi=(0.1, 0.0, 0.9, 0.45),
                     src_radius=76, num_flare_circles_range=(1, 3), p=0.15),
    A.AdvancedBlur(blur_limit=(3, 5), p=0.1),
], seed=42, strict=True)
# 輸入為 RGB uint8；OpenCV 讀圖為 BGR，使用前須轉換。
# augmented = transform(image=rgb_image)["image"]
```

`p` 是對候選圖套用該效果的機率，不是最終資料集比例。`RandomGamma` 不是 Roboflow Exposure 的數值等價替代。`RandomSunFlare` 模擬鏡頭耀斑／光暈，不能完整代表濕柏油路面的方向性反射；仍需真實雨夜與積水資料。[Albumentations 2.0.8 原始碼與參數](https://raw.githubusercontent.com/albumentations-team/albumentations/2.0.8/albumentations/augmentations/pixel/transforms.py)

課程預設 AdvancedBlur 低機率、小核心。GlassBlur 並不是濕路面物理模型，且可能使邊界外觀明顯扭曲，不放入預設管線；若做進階比較，可單獨替換為 `A.GlassBlur(sigma=0.5, max_delta=1, iterations=1, p=0.05)`，重新複核標記與影像是否仍合理。[模糊變換文件](https://albumentations.ai/docs/api-reference/albumentations/augmentations/blur/transforms/)

**為何 TXT 可以直接複製？** 本腳本只修改外觀，不做裁切、旋轉、縮放、透視或翻轉。因此保留原多邊形座標。若自行加入幾何變換，必須讓影像與多邊形／遮罩同步轉換，不能延用此複製方式。

打開 `datasets/road_aug/qc`，前 30 組比較圖左側為原圖、右側為候選圖，綠線為標記邊界。檢查強光是否完全吞沒邊界、色調是否離譜、道路是否仍可辨識。抽查其他候選圖；不合理時調弱參數並產生新版本。這是人工品質關卡，程式沒有自動判定「反光合理」。

公平的離線增強對照，先保持與 A 相同的訓練 profile：

```powershell
python training/road_reflection/train.py --data datasets/road_aug/data.yaml --profile baseline --name C_offline --epochs 50 --batch 8 --device 0
```

若出現增強疊加過強，再以 `--profile stacked --name D_reduced` 做另一組實驗。Roboflow 的 `v2_rf_light` 也應獨立準備成新資料夾，搭配 baseline 先比對；不要先和本地增強混合，否則難以判斷效果來自哪一層。

## 9. 驗證、預測與分場景比較

### 9.1 YOLO 標準驗證

```powershell
yolo segment val model=runs/road/A_base/weights/best.pt data=datasets/road_base/data.yaml split=val imgsz=640 device=0
yolo segment predict model=runs/road/A_base/weights/best.pt source=datasets/road_base/valid/images imgsz=640 conf=0.25 save=True project=runs/road name=A_preview
```

以相同方式評估 B 與 C，關注 **mask mAP50-95**，不要只看 box mAP。mAP 衡量實例分割，不直接等於道路像素 IoU 或車道中心穩定性。[分割模式](https://docs.ultralytics.com/tasks/segment/)

### 9.2 依天候與光線評估道路像素

建立 `datasets/valid_scenes.csv`，一列對應 road_base/valid/images 中每一張**匯出後實際檔名**：

```csv
file,scene
rain01_000001.jpg,rain_glare
rain01_000002.jpg,rain_glare
day03_000001.jpg,day_normal
night03_000001.jpg,night_glare
```

Roboflow 可能改寫檔名，不能不加核對就沿用 frames.csv。可依 clip_id 前綴追溯；每張需人工確認 scene。建議採 day_normal、day_glare、rain_glare、night_glare 四組，互斥且都有足夠獨立場次。

```powershell
python training/road_reflection/evaluate.py --model runs/road/A_base/weights/best.pt --data datasets/road_base/data.yaml --scenes datasets/valid_scenes.csv --output runs/road/A_pixels.json --device 0
python training/road_reflection/evaluate.py --model runs/road/B_yolo/weights/best.pt --data datasets/road_base/data.yaml --scenes datasets/valid_scenes.csv --output runs/road/B_pixels.json --device 0
python training/road_reflection/evaluate.py --model runs/road/C_offline/weights/best.pt --data datasets/road_base/data.yaml --scenes datasets/valid_scenes.csv --output runs/road/C_pixels.json --device 0
```

腳本將所有 road 實例合併，以原圖大小比較：

- `road_iou = TP / (TP + FP + FN)`：道路像素交集／聯集，越高越好。
- `road_recall = TP / (TP + FN)`：道路被正確保留的比例，越高越好。
- `background_fpr = FP / (FP + TN)`：背景被錯標成道路的比例，越低越好。

分組摘要採累加像素後計算，解析度較大影像權重較高；逐張分數也保存在 JSON。分母為零輸出 `null`，不是零分或滿分。背景 FPR 不是「反光區誤判率」：若要只測反光區，另標高亮區遮罩，限定在該區統計。對真道路上的反光，優先看漏檢與邊界偏移；對牆面等非道路反光，才是背景誤檢。

### 9.3 實驗報告

| 實驗 | 輸入 | 訓練 profile | mask mAP50-95 | 雨反光 IoU | 夜反光 IoU | 正常白天 IoU |
|---|---|---|---|---|---|---|
| A | road_base | baseline | 實測 | 實測 | 實測 | 實測 |
| B | road_base | reflection | 實測 | 實測 | 實測 | 實測 |
| C | road_aug | baseline | 實測 | 實測 | 實測 | 實測 |
| D（選做） | road_aug | stacked | 實測 | 實測 | 實測 | 實測 |

保持相同 pretrained 權重、尺寸、batch、seed、epochs 與驗證集；不從 A 的 best.pt 繼續訓練 B。C 的資料增加使同樣 epochs 有更多 optimizer steps，因此結果也受計算量影響；報告記錄圖片數、訓練時間，嚴格比較可另做等步數實驗。重要結論用 seed 42／43／44 重複，報告平均與差異。

判定標準應在看結果前訂好，例如「反光組 IoU 提升、正常白天 IoU 不下降超過 0.02、邊界錯誤案例減少」。此數字只是課堂範例，不能視為車輛安全門檻。

選好方案後，以它的 best.pt 在 test 做一次最終評估：

```powershell
yolo segment val model=runs/road/B_yolo/weights/best.pt data=datasets/road_base/data.yaml split=test imgsz=640 device=0
python training/road_reflection/evaluate.py --model runs/road/B_yolo/weights/best.pt --data datasets/road_base/data.yaml --scenes datasets/test_scenes.csv --split test --output runs/road/final_test.json --device 0
```

這裡 B 只是路徑範例，請替換為驗證後勝出的模型。test_scenes.csv 必須覆蓋 test 實際檔名。若看完測試集再持續調參，該集合已成開發資料，需要另一份獨立最終測試集。

### 9.4 影片閃爍檢查

```powershell
yolo segment predict model=runs/road/B_yolo/weights/best.pt source=videos/heldout.mp4 imgsz=640 conf=0.25 save=True project=runs/road name=heldout_video
```

在未參與訓練的連續影片，逐段比較遮罩缺失幀、邊界跳動與反光出現前後的中心線變化；所有模型使用相同門檻。靜態影像增強不直接保證時序穩定。本課程附的評估程式只算靜態像素指標，影片抖動需要另外記錄，不能從 IoU 推定。

## 10. 匯出模型與 Raspberry Pi 5 銜接

先在原始 PyTorch 權重驗證成功，再匯出：

```powershell
yolo export model=runs/road/B_yolo/weights/best.pt format=onnx imgsz=640
yolo export model=runs/road/B_yolo/weights/best.pt format=ncnn imgsz=416 batch=1
```

ONNX 適用支援的執行環境；本專案 Pi 路線使用 NCNN。TensorRT 是 NVIDIA 平台路線，不適用沒有 NVIDIA GPU 的 Pi 5；需在相容 NVIDIA 環境另行匯出與驗證。匯出可能要求安裝相應依賴。[匯出支援表](https://docs.ultralytics.com/modes/export/)

訓練 640、部署 416 是額外變因，請在 **416 與實際匯出模型**重跑評估，不能直接引用 640 的成績。以終端顯示的匯出資料夾為準：

```powershell
yolo segment val model=runs/road/B_yolo/weights/best_ncnn_model data=datasets/road_base/data.yaml imgsz=416 device=cpu
```

本專案 `autocar/config.py` 目前預設 `AUTOCAR_LANE_CLASS=lane`；新模型是 `road`。部署時在既有服務設定使用：

```dotenv
AUTOCAR_LANE_MODEL=models/road_best_ncnn_model
AUTOCAR_LANE_CLASS=road
AUTOCAR_INFERENCE_IMGSZ=416
```

將實際 NCNN 資料夾放到對應路徑，再依[部署備忘錄](DEPLOYMENT_MEMO_ZH_TW.md)操作。道路表面中心不必然等於行車道中心，多車道、路口、障礙物情境尤其如此；類別設定銜接不代表控制策略已驗證。先離線影片、再靜止取景檢查，最後才在受控場地驗證車體。教材沒有變更現有車控或部署中的模型。

## 11. 常見問題與進階練習

| 問題 | 檢查與處理 |
|---|---|
| ffmpeg 不是可辨識的命令 | 重新開 PowerShell，檢查 PATH 是否含 FFmpeg 的 bin |
| 抽出的畫面太相似 | 增大 interval、去除停車片段、補拍不同場次 |
| 標記格式錯誤／沒有 segmentation labels | 檢查是否匯出偵測框五欄格式、是否缺 TXT |
| 找不到資料夾 | 檢查 data.yaml 絕對 path、valid 與 val 命名 |
| CUDA out of memory | batch 8 改 4／2；必要時降 imgsz，並讓對照模型同步調整 |
| 載入 yolo26n-seg.pt 失敗 | 核對 Ultralytics 版本、模型檔名與下載網路 |
| 模糊／耀斑參數不接受 | 核對 Albumentations 是否為 2.0.8，勿混用舊參數名稱 |
| 訓練分數高，上車反光仍漏檢 | 查場次洩漏、相機角度／曝光差異、場景比例與 416 尺寸表現 |
| 載入新模型卻沒有道路輸出 | 查 class 名稱是否為 road，以及部署大小、權重與路徑 |

進階練習優先順序：①補真實失敗樣本並複核標記；②一次調一項增強；③比較較高解析度與模型大小；④再考慮損失函數或架構。`box`／`cls` 等一般 loss gain 不是道路邊界 loss；不要捏造 `boundary_loss=True` 之類訓練參數。若實作 Dice 或 boundary loss，需另建自訂 trainer／loss、單元測試與對照實驗，不屬本課程入門流程。

過曝像素若已飽和，原始紋理資訊就已遺失。目標是利用還可見的邊界、上下文與更多真實例子減少錯誤，而不是保證「看穿」完全不可見的路面。對比度與灰階也不能完整模擬霧、雨滴或濕路面的成像。

## 12. 作業繳交與完成標準

繳交影片分組 CSV、資料版本／標記規則、10 張標記複核圖、增強比較圖、環境版本紀錄、A／B／C 設定與評估表，以及至少 5 個失敗案例。每個失敗案例說明實際場景、誤檢或漏檢位置、下一步要改資料還是參數。

完成標準是「流程可重現、集合獨立、比較有依據」，不以虛構的精度目標驗收。若增強沒有改善，保留基準並說明原因也屬有效實驗。課程範例不是已在你的影片上訓練完成的模型。

教材交付時，以 Python 3.10、Albumentations 2.0.8 與合成影像／影片驗證了抽幀張數、場次防洩漏、多邊形格式檢查、增強執行、標籤與 valid／test 保持一致、相同種子重現，以及評分公式。尚未使用你的實景影片，也未執行 YOLO GPU 訓練、真實模型推論或 NCNN 匯出；實際精度與車載效果須依本課程流程驗證。