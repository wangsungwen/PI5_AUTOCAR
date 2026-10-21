# AutoCAR UE4 可切換室內場景原型

此專案參考使用者提供的室內道路影像，提供三個可切換的場景。這是**幾何與相機巡覽原型**，不是已校準的實景數位分身，也不是已完成的 AirSim 自駕環境。

## 目前可以看什麼

直接開啟 `preview/index.html`，可用按鈕或 1／2／3 切換三組預覽，按 C 切換車載視角與俯視配置圖。此頁不需要網路或額外套件。

預覽由與 UE4 相同的幾何資料繪製，但不是 UE4 渲染：沒有重現 Unreal 光照、材質反射、抗鋸齒或真實相機成像。

| 場景 | 內容 | 參考 |
|---|---|---|
| 1 木紋地板彎道 | 木紋板條、白色膠帶、緩彎、櫃體和紙箱簡模 | datasets/road_export 中的道路圖片 |
| 2 亮面地板路段 | S 形車道、低粗糙度地板材質與較亮燈光設定 | 20260915 的地板反光影片 |
| 3 紅綠燈測試區 | 直道、停止線、小型燈號模型 | 20261013、output2、1151013 影片 |

三個配置是依場景特徵設計的測試布局，並非從影片精確量測出的三張地圖。停止線為測試設計，不宣稱原場地有相同標線。沒有將原始圖片當成平面背景冒充 3D。

## UE4 啟動

需要 Windows、Unreal Engine **4.27** 編輯器，以及相容的 Visual Studio C++ 工具鏈（含 Windows SDK）。只有已封裝的 AirSimNH.exe 無法編譯或新增本專案的模型及程式。

首次執行：

```powershell
cd D:\ResearchCodes\RPI5_AutoCAR_RoadTrain\sim_ue4
.\launch.ps1 -EngineRoot "C:\Program Files\Epic Games\UE_4.27" -Prepare
```

`-Prepare` 會編譯本專案，透過 UE4 Python 建立材質和 `Content/Maps/Indoor.umap`，再開啟編輯器。按 Play 開始；Play 尚未開始時，地圖是空白的，場景由執行時程式生成。若 PowerShell 執行原則阻擋，可用 `powershell -ExecutionPolicy Bypass -File .\launch.ps1 ...` 啟動此腳本。

之後開啟獨立遊戲視窗：

```powershell
.\launch.ps1 -EngineRoot "C:\Program Files\Epic Games\UE_4.27" -Game
```

此方式仍使用 UE4Editor 執行本專案，並非獨立封裝好的 EXE。需要獨立 EXE 時，必須在 UE4 編輯器完成編譯與實機確認後再 Package Windows；設定已包含地圖、動態載入材質與 Data 資料目錄。

## 操作

| 操作 | 功能 |
|---|---|
| 上方按鈕或 1／2／3 | 替換場景幾何、燈光及相機起點，燈號回到紅燈 |
| W／S | 以暫定速度向前／向後巡覽 |
| A／D | 原地轉向；尚非真實車輛轉向模型 |
| Space | 按住時不移動或轉向 |
| R | 回到目前場景的初始車載視角 |
| C | 切換俯視／車載視角；俯視時停止移動 |
| T | 場景 3 燈號：紅 → 綠 → 黃 → 紅 |

相機移動僅限制在房間範圍內，**尚無物件碰撞、輪胎／馬達動力學、道路跟隨或紅燈自動停車**。紅綠燈由手動控制，並非自動週期。

## 調整場地與相機

編輯 `scene_config.json`，目前暫定：

- 房間 800 × 600 cm，牆高 260 cm。
- 車道兩側白線中心距 58 cm，白線寬 2.5 cm。
- 相機距地面 15 cm，俯角 8°，水平 FOV 66°。
- 巡覽速度 35 cm/s，轉向速度 65°/s。
- `control_points` 是各場景的道路中心線控制點；`signal_position` 是燈座中心。

所有這些值都需要實測確認，FOV 也不代表已完成相機標定。相機高度和鏡頭內參對低視角道路形狀尤其重要。房間尺寸和路徑控制點獨立，改房間大小時也應調整路徑與物件配置；驗證會檢查車道是否超出房間。

修改後執行：

```powershell
python tools/generate_scenes.py
python tools/validate_scenes.py
python tools/render_preview.py
```

前兩步只用 Python 標準函式庫。預覽繪製需要 `numpy` 和 `Pillow`。重新切換場景可讀入新的幾何 JSON；材質粗糙度則在 `tools/prepare_editor.py` 修改，需再次 `-Prepare`。

## 驗證與限制

已執行幾何資料驗證：三組不同路徑、相機值、道路界線、三角形索引、非退化面、法線與顏色範圍。已產生並目視檢查三組預覽。

建立本版時，沒有在已檢查的位置找到 UE4 編輯器或 Visual Studio C++ 工具鏈。因此 **UE4 C++ 編譯、材質建立、執行時切換、封裝均尚未實測**。`validation.json` 保留了此狀態，不把資料驗證當成 UE4 執行成功。

尚未修改現有 AirSimNH、AirSim settings.json 或實車控制。此專案不提供 AirSim RPC；接入現有 `sim_airsim` 前還需加入相容的 AirSim plugin、適合小車尺寸的 vehicle pawn、碰撞與相機配置。不可直接把 AirSim 全尺寸汽車放進 58 cm 車道後當成真車等效驗證。

原始影像只抽樣查看，沒有逐幀重建、攝影測量或實際尺寸校準。地板木紋目前是程序化簡化幾何；亮面材質僅設置粗糙度與照明，反射是否吻合須在 UE4 中另行比對。

UE4 驗收時依序檢查：啟動場景 1；用滑鼠和數字鍵逐一切換；多次切換確認沒有殘留燈光或幾何；檢查 R/C；場景 3 按 T 確認燈號循環；最後比對實拍與相機視角。

## 實作參考

- [UE4.27 ProceduralMeshComponent](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/ProceduralMeshComponent?application_version=4.27)
- [UE4.27 MaterialEditingLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialEditingLibrary?application_version=4.27)
