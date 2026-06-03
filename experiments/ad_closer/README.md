# Ad Closer 支線實驗

> ⚠️ **此目錄與主線 Valor Legends bot 完全分離**
> 不會被 `src/main.py` 呼叫，不干擾每日任務 / navigation graph。

---

## 1. 這是什麼

用來驗證以下核心能力的獨立實驗腳本：

| 能力 | 驗證方式 |
|---|---|
| ADB 截圖（記憶體模式） | `DeviceController.screenshot()` |
| OpenCV template matching | `VisionMatcher.match_templates()` |
| 座標 tap | `DeviceController.tap(cx, cy)` |
| Timeout 機制 | 整個流程設定總上限 |
| Debug screenshot 輸出 | FAILED 時自動存圖，帶 bbox 紅框 |

**目前不會整合到每日任務主線。** 等各項能力驗收後，才會考慮納入主流程。

---

## 2. 目錄結構

```
experiments/ad_closer/
├── run_ad_closer.py        ← 支線入口（自包含，可直接執行）
├── assets/
│   ├── ad_close/           ← 放廣告關閉按鈕的 template PNG
│   │   ├── close_x_01.png  （你自己裁切的）
│   │   ├── close_x_02.png
│   │   └── skip_01.png
│   └── anchors/
│       └── game_lobby_anchor.png  ← 遊戲大廳特徵圖（可選）
├── debug/                  ← debug 模式自動輸出截圖（git ignore）
└── README.md               ← 本文件
```

---

## 3. 如何放 Template

Template 是告訴腳本「什麼樣子的按鈕要點」的參考圖片。

### 步驟

1. **擷取截圖**：在廣告播放接近尾聲時（X / Close / Skip 按鈕出現時），執行：
   ```powershell
   .\.venv\Scripts\python.exe src/main.py screenshot
   # 截圖存到 screenshots/current.png
   ```

2. **裁切按鈕區域**：
   - 用 Paint / IrfanView / Photoshop 開啟 `screenshots/current.png`
   - 框選廣告的 **X / Close / Skip 按鈕本身**（不含太多背景）
   - 建議大小：約 **40×40 ~ 100×80 px**
   - 存為 PNG，命名如 `close_x_01.png`

3. **放入本目錄**：
   ```
   experiments/ad_closer/assets/ad_close/close_x_01.png
   ```

4. 可以放**多張**不同廣告的按鈕，腳本會自動選信心值最高的那張。

### 注意事項
- Template 解析度必須與模擬器截圖一致（全部在同一個解析度下裁切）。
- 不要裁太大（會含入變動背景），也不要太小（只有幾個像素容易誤判）。
- `assets/anchors/game_lobby_anchor.png` 是**選填的**：放遊戲大廳固定 UI 特徵（例如底部導覽圖示），用來確認廣告確實已關閉並回到遊戲。若不存在，腳本改用「close button 消失」判斷。

---

## 4. 如何執行

> 所有指令請從**專案根目錄**（`E:\antigravity\adb_vl`）執行。

### 快速執行（預設參數）
```powershell
# 1. 手動在遊戲點開一個廣告
# 2. 立刻執行腳本
.\.venv\Scripts\python.exe experiments/ad_closer/run_ad_closer.py --debug
```

### 完整參數
```powershell
.\.venv\Scripts\python.exe experiments/ad_closer/run_ad_closer.py `
    --serial 127.0.0.1:5555 `
    --initial-wait 30 `
    --interval 1.0 `
    --timeout 90 `
    --threshold 0.82 `
    --debug
```

### 所有 CLI 參數說明

| 參數 | 預設值 | 說明 |
|---|---|---|
| `--serial` | `127.0.0.1:5555` | ADB 設備 serial |
| `--initial-wait` | `30` | 廣告載入等待秒數（不掃描） |
| `--timeout` | `90` | 整個流程總上限（含 initial-wait） |
| `--interval` | `1.0` | FIND 階段每次截圖間隔（秒） |
| `--threshold` | `0.82` | Template matching 信心值閾值 |
| `--anchor-threshold` | `0.80` | Anchor 偵測信心值閾值 |
| `--ad-close-dir` | `assets/ad_close/` | Close template 資料夾 |
| `--anchor-path` | `assets/anchors/game_lobby_anchor.png` | 遊戲大廳 anchor |
| `--post-tap-wait` | `2.5` | TAP 後等待秒數 |
| `--max-taps` | `5` | 最大 TAP 嘗試次數 |
| `--debug` | False | 輸出帶 bbox 的 debug 截圖 |
| `--debug-dir` | `debug/` | Debug 截圖輸出目錄 |

> **Timeout 定義**：整個流程的總時間（含 initial-wait）。
> 例：`--initial-wait 30 --timeout 90` → 前 30s 不掃描，後 60s 掃描，共 90s 上限。

---

## 5. 狀態機流程

```
執行 run_ad_closer.py
         │
  [INITIAL_WAIT]
    ├─ 固定 sleep initial_wait_seconds（預設 30s）
    ├─ 每 5s 輸出倒數進度
    └─ 不截圖、不 matching、不點擊
         │
  [FIND_CLOSE_OR_SKIP]
    ├─ 每 interval 秒（預設 1s）截圖一次
    ├─ 掃描四角 ROI
    │    top_right (0~20%, 70~100%)    ← 最常見 X 位置
    │    top_left  (0~20%, 0~30%)
    │    bottom_right (80~100%, 70~100%) ← Skip Ad
    │    bottom_left  (80~100%, 0~30%)
    ├─ 每次輸出：elapsed / confidence / template / ROI
    └─ 找到目標 → TAP_CLOSE
         │
  [TAP_CLOSE]
    ├─ adb tap center
    ├─ 等 post_tap_wait（2.5s）
    ├─ 確認結果：
    │    anchor 通過 → DONE ✅
    │    close button 消失 → DONE ✅
    └─ close button 仍在 → 更新目標，重試 TAP_CLOSE
         │
  [DONE]  ✅ 廣告關閉成功
  [FAILED] ❌ timeout / max_tap 超過 → 儲存 debug 截圖，不 back、不重啟
```

---

## 6. 如何查看 Debug Screenshot

執行時加上 `--debug` 後，截圖輸出到 `experiments/ad_closer/debug/`：

| 檔名格式 | 說明 |
|---|---|
| `find_XXs_HHMMSS.png` | FIND 掃描時的 debug 圖（帶紅框 bbox + 綠點 center） |
| `post_tap_check_HHMMSS.png` | TAP 後確認 close button 是否仍在 |
| `raw_find_XXs_HHMMSS.png` | 原始裸截圖（無框，debug 模式下同步儲存） |
| `failed_YYYYMMDD_HHMMSS.png` | FAILED 時的最後截圖（無框，供分析） |

**排查步驟**：
1. 確認 `failed_*.png` 中廣告畫面是否正常（不是黑屏）。
2. 確認 `find_*.png` 中的紅框位置是否對到 close button。
3. 若信心值偏低（例如 0.3~0.6），表示 template 品質不夠好，需重新裁切。

---

## 7. 與主線的關係

```
src/main.py              ← 主線入口（每日任務、navigation graph）
  └─ probe-daily-tasks   ← 主線指令，不動
  └─ screenshot / tap / find  ← 主線工具，不動

experiments/ad_closer/
  └─ run_ad_closer.py   ← 支線入口，完全獨立
```

- 兩者**不共用狀態**，不共用 loop，不互相呼叫。
- 若未來確認廣告關閉功能穩定，再評估是否納入主線。
- 共用的底層工具（`src/adb_controller.py`、`src/vision_matcher.py`）只被 import，不被修改。
