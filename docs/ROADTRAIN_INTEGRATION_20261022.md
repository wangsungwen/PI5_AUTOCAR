# RoadTrain 整合與自走推論檢查（2026-10-22）

## 維護位置與整合決策

統一維護根目錄：`D:\ResearchCodes\RPI5_AutoCAR`。
原始 RoadTrain 與完整雙版本 `RPI5_AutoCAR_AirSim_Pi5` 均未修改。
本次沒有操作實車、遠端部署或自動提交 Git；整合前既有的未提交修改已保留。

- `autocar/`：採納 RoadTrain 的錄影 encoder 停止修正、前進／倒車檔位與模擬器影像介接。
- `web/`：採納新版分頁介面、全域停止、檔位選擇、雙端錄影介面；保留單一套板端與 PC 共用網頁。
- `training/`：相同程式只留一份。保留主專案較完整的 `train_traffic.py`（資料檢查、三類或四類、最佳權重評估與匯出），不以 RoadTrain 的簡化版覆蓋。
- `prepare.py`：納入 `Road-Area`／`road-area` 類別相容；仍要求新的輸出目錄，不移植 RoadTrain 直接遞迴刪除輸出的 `--overwrite`。
- `datasets/`、`runs/`、`weights/`、基礎 `yolo26n-seg.pt`、原始資料 ZIP、`sim_runs/`：已複製到統一根目錄。`datasets/road_base/data.yaml` 已改為主專案位置。
- `sim_airsim/` 與 `sim_ue4/`：納入 RoadTrain 的模擬器來源，維持既有路徑與匯入；不取代第三個專案的最終架構。
- `docs/`：納入補充文件；RoadTrain 原 README 另存 `ROADTRAIN_ORIGINAL_README.md`，其中歷史路徑與結果保留原文。
- 不搬移虛擬環境、Python 快取、舊網頁備份及根目錄重複教材／錄影。它們仍在原 RoadTrain，不影響已整合程式入口。

逐檔來源 SHA-256 與決策見 `ROADTRAIN_MERGE_MANIFEST.json`。整合前備份位於：
`D:\ResearchCodes\RPI5_AutoCAR\.build_artifacts\pre-roadtrain-20261022-061800`。
備份含原始碼、設定、測試、文件、README 及 .gitignore；新增檔案可依清單識別。不是整個磁碟／資料集備份。

## 已修正的控制與推論問題

1. 停止與馬達寫入共用鎖；停止先送零 PWM，再等待工作執行緒。推論晚回傳也不能重新驅動。
2. 舊工作執行緒尚未退出時拒絕重新啟動，避免共用停止事件被清除後舊執行緒復活。每次啟動清除前次影像、燈號與遙測。
3. 道路模型初始化納入例外處理；必要燈號模型失敗會停止並回報，而不是只留背景例外。
4. 道路影像在道路推論前發布給燈號工作執行緒；每張擷取影像有序號，同一張不重複投票，並避免每次輪詢複製整張影像。
5. 燈號結果以擷取時刻判定新鮮度，不能因慢推論完成而把舊影像變成新資料。道路結果超過 watchdog 時限也不送前進命令。
6. 新紅燈／停止標誌會清除危險出現前的通行票數；解除需累積新觀測，不能被先前綠燈多數票立即解除。
7. PID 啟動／重置後第一筆不產生微分突波；轉向限制於當前速度，避免黃燈減速時內側輪反轉。
8. 道路遮罩使用還原到原圖的 `masks.xy` 多邊形，不直接拉伸含 letterbox 補邊的推論遮罩。依據 [Ultralytics Masks.xy 文件](https://docs.ultralytics.com/reference/engine/results/#ultralytics.engine.results.Masks.xy)。
9. 模型類別不匹配時回報明確錯誤；燈號推論明確指定 CPU，符合 Pi 執行路徑。
10. 打包納入新增模組、網頁與模擬器來源；增量包 manifest 涵蓋全部 autocar、web、tests、sim_airsim 檔案。

## 驗證結果與限制

- 完整 AI 環境：48 項 Python 單元／回歸測試通過，含停止競態、初始化失敗、慢道路結果、影像去重、時間戳、黃燈轉向與遮罩座標。
- 網頁 Node 測試通過；Python 編譯檢查通過。
- 完整測試使用既有 RoadTrain `.venv` 的 Python 3.11 / Ultralytics 8.4.173；沒有複製不可搬移的虛擬環境。基礎 Anaconda 缺 OpenCV 時兩項幾何測試會明確跳過。
- 真實 `.pt` 權重離線載入成功。道路類別為 `road`；燈號權重有 `red_light, yellow_light, green_light, stop_sign`。
- `baseline_v1-2/weights/best.pt` 在 `datasets/road_base/test/images` 的 5 張影像、416 與 640 尺寸、confidence=0.3 下均無有效道路觀測。單張直接 Ultralytics 推論也回傳空 boxes，並非單純 ROI 中心計算造成。結果在 `ROAD_MODEL_CHECK_20261022.json`。
- `PERCEPTION_SMOKE_20261022.json` 是單張離線流程檢查，燈號結果 NONE；不是燈號精度、停止標誌召回率或硬體延遲測試。
- 未進行重新訓練、NCNN 匯出／實測、實車 GPIO／相機／網路端到端測試。未把歷史訓練 CSV 的高分當成本次模型可用證據。

## 執行與部署銜接

在主專案根目錄執行。新環境依 `requirements.txt`、`requirements-autonomy.txt` 與所需的 `training/*requirements*.txt` 安裝，Pi 安裝依原 `scripts/install_pi.sh` 文件。

```powershell
python -m unittest discover -s tests -v
node tests/test_manual_ui.js
python training/road_reflection/prepare.py --source datasets/road_export --output datasets/road_checked
python training/train_traffic.py --data training/traffic_light.yaml --check-only
```

最後一條需要先依 YAML 配好燈號資料。本次 RoadTrain 內只有道路資料與燈號訓練產物，沒有完整燈號訓練影像集；無法從權重還原資料集。

離線推論範例（IMAGE.jpg 換成實際影像）：

```powershell
python scripts/check_perception.py --lane-model runs/segment/runs/road/baseline_v1-2/weights/best.pt --traffic-model runs/detect/kingfisher-raccoon-2/traffic-light/train/weights/best.pt --image IMAGE.jpg
```

權重通過離線評估後，才匯出與實際輸入尺寸一致的 NCNN 模型並部署。道路新模型使用以下設定；舊 `lane` 模型的預設設定刻意保留以免破壞既有板端：

```dotenv
AUTOCAR_LANE_MODEL=models/road_best_ncnn_model
AUTOCAR_LANE_CLASS=road
AUTOCAR_MODEL=models/traffic_best_ncnn_model
AUTOCAR_INFERENCE_IMGSZ=416
AUTOCAR_LANE_REQUIRED=1
AUTOCAR_TRAFFIC_REQUIRED=1
```

目前整合進來的是 `.pt`，不是上述路徑的 NCNN 成品；不可只改設定就認定可啟動。
`AUTOCAR_LANE_BACKEND=opencv` 作為替代方案時需明確設定 `AUTOCAR_LANE_REQUIRED=0`。
道路訓練程式輸出名稱以終端列出的實際 best checkpoint 為準。

重新打包：`python scripts/package_release.py`。原始碼 ZIP 不含 datasets、runs、weights、模型或虛擬環境；需要離線搬機時另外攜帶這些資料。現有訓練紀錄的 args.yaml 保留歷史絕對路徑，重新訓練請使用主專案內的資料 YAML。

## 下一階段優化優先順序

1. 先查道路權重與訓練環境／資料版本是否一致，使用相同環境重跑帶標記驗證集，釐清空偵測；不要靠降低門檻直接上車。
2. 收集不同拍攝場次的道路與反光、燈號及停止標誌，依場次切分，避免相鄰影格洩漏。
3. 在 Pi 量測雙模型加上預覽的延遲分布，再決定推論頻率與尺寸。現有預覽仍是另一個推論工作，資源不足時可考慮共用推論結果；本次未直接改變預覽產品行為。
4. 道路區域質心不等於可通行車道中心；多車道、路口及分離區域需增加連通區／路徑選擇與障礙物策略，並以標記影片評估後再改控制。
5. 停止標誌目前是可見即停、後續非危險觀測投票解除，尚不是完整「停滿秒數、路口確認、冷卻解除」狀態機；紅燈遮蔽時的解除規則也需按實驗場景定義。
