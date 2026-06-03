# Project Audit — adb_vl（Valor Legends ADB 自動化工具）

> 審計時間：2026-06-03  
> 審計方式：純靜態閱讀，未執行任何指令、未修改任何檔案

---

## 1. 專案真正目標是什麼

**目標**：透過 ADB 截圖 + OpenCV template matching + ADB tap，對 Valor Legends 遊戲進行純外部 UI 自動化。

核心設計守則（已在多處文件重複確認）：
- 不封包攔截、不記憶體修改、不 APK 注入
- 失敗時停止並輸出 `STOPPED_FOR_HUMAN_REVIEW`，不盲目重試
- 只做低風險操作（不消耗鑽石、召喚券、次數）

**目前實際執行到的功能**（已驗證）：
- 每日任務「前往」按鈕探測（probe-daily-tasks）
- 無盡試煉進入→戰鬥→結算的完整流程（run-small-tasks）

---

## 2. 目前的分支（Branch）列表

| 分支名稱 | 路徑 | 狀態 |
|---|---|---|
| **每日任務 probe** | `src/actions.py::probe_daily_tasks_action` | ✅ 已驗證過（但有去重誤判紀錄） |
| **run-small-tasks（無盡試煉＋戰役）** | `src/actions.py::run_small_tasks_action` | ✅ 已驗證過（硬編碼座標） |
| **無盡試煉 Vision-Guided Route** | `experiments/endless_trial_route/run_endless_trial.py` | 🔄 有實際執行紀錄（今日），尚未成功完整跑完（待確認） |
| **競技場 Route** | `experiments/arena_route/run_arena.py` | 🔄 今日有執行紀錄，進了競技場多人頁，但未見成功結束 |
| **廣告關閉** | `experiments/ad_closer/run_ad_closer.py`、`src/ad_closer.py` | 🔴 pure experiment；assets 目錄存在但無實際 template 圖片 |
| **競技場 OCR（戰力辨識）** | `src/ocr_utils.py` + scratch/analyze_arena*.py | 🔴 scratch 層實驗；hash-map based，高度脆弱 |
| **各路線 route 骨架** | `experiments/{midas/bounty/campaign/secret/summon/time_travel}_route/` | 🔴 只有 assets/scenes 目錄，尚無執行腳本 |

---

## 3. 目前應優先的主線

**主線：`experiments/endless_trial_route/run_endless_trial.py`**

理由（以文件為依據）：
1. 唯一有完整 **vision-guided** 架構（scene anchor detection → 場景判斷 → 對應動作）的執行腳本
2. 今日 debug 目錄中留有大量 `step_20260603_*` 截圖，顯示確實有執行記錄
3. 有完整的 10 個 scene anchor（`001_daily_tasks` 到 `008_exit_confirm`）
4. `docs/endless_trial_mvp_design.md` 有完整設計規格（最詳細的一份文件）
5. 最低風險：無盡試煉不消耗有限資源（次數）

> [!NOTE]
> 競技場 route 也有執行紀錄（今日 18:xx），但其 `run_arena.py` 依賴 `ocr_utils.py`（hash OCR），並且 debug 日誌顯示它在「多人競技場」頁面重複停留，未見清晰成功退出，風險比無盡試煉更高（需要讀取戰力來選對手）。

---

## 4. 正式主線 vs Experiment/Scratch

### 正式主線（Production-ready 或接近）
| 檔案 | 說明 |
|---|---|
| `src/adb_controller.py` | DeviceController 底層（連線、截圖、tap、back） |
| `src/vision_matcher.py` | VisionMatcher（ROI、multi-template、debug 框） |
| `src/adb_client.py` | 舊版 ADB 底層（仍是 probe-daily-tasks 的依賴） |
| `src/vision.py` | 舊版 vision（find_template） |
| `src/actions.py` | probe-daily-tasks / run-small-tasks CLI 邏輯 |
| `src/main.py` | CLI 入口 |
| `data/status_graph.json` | 導航圖 JSON（節點+邊+驗證狀態） |
| `experiments/endless_trial_route/run_endless_trial.py` | Vision-guided 無盡試煉主程式 |
| `experiments/endless_trial_route/assets/scenes/` | 10 個 scene anchor（已建立） |

### Experiment（參考/備用）
| 檔案 | 說明 |
|---|---|
| `experiments/arena_route/run_arena.py` | 競技場路線，依賴 OCR |
| `experiments/ad_closer/run_ad_closer.py` | 廣告關閉，template 尚未齊備 |
| `src/ad_closer.py` | 廣告關閉狀態機（未掛入 main） |
| `src/ocr_utils.py` | 競技場戰力 hash OCR（脆弱） |

### Scratch（一次性分析腳本，不是主線）
- `scratch/` 目錄：105+ 個 analyze_*.py / crop_*.py / find_*.py 腳本
- 用途：截圖分析、anchor 裁切、OCR 測試、像素檢查
- **不應視為功能實作的一部分**

---

## 5. 功能驗證狀態

### 已驗證（有截圖/執行紀錄為證）

| 功能 | 驗證依據 |
|---|---|
| ADB 連線 / 截圖 / tap | `status_graph_observations.md` 記錄完整執行紀錄 |
| daily_tasks 頁面辨識（template matching） | overlay 截圖：confidence=1.0000，`daily_tasks_title.png` |
| 「前往」按鈕 (go_button.png) 掃描 | overlay 截圖：confidence=0.8997，找到 (1399, 414) |
| probe-daily-tasks 完整執行（1次成功） | `probe_001_before/after.png` 存在 |
| daily_tasks → endless_trial 跳轉 + Back 返回 | `status_graph_observations.md` Verified |
| main_campaign → daily_tasks 跳轉 | status_graph.json confidence=0.92, Verified |
| run-small-tasks 無盡試煉完整執行 | `task_run_observations.md`（進入、戰鬥、返回成功） |
| run-small-tasks 戰役完整執行 | `task_run_observations.md`（雙擊結算後成功） |
| endless_trial_route scene 辨識可以識別各場景 | 今日 debug 截圖（002/003/004/005 等 scene） |

### 待驗證（有設計但未有成功執行紀錄）

| 功能 | 說明 |
|---|---|
| endless_trial_route 完整一次循環成功 | 有執行紀錄，但有重複進入 battle 的跡象，未見 DONE 輸出 |
| Context-Aware Entry（從 daily_tasks 啟動） | README 有設計，code 有 001_daily_tasks 場景，但 debug 截圖顯示多次從 002_trial_lobby 開始 |
| 戰鬥結束後 battle_end 的後續處理（unknown scene）| `005_battle_end` 後連續出現 unknown，見下方失敗記錄 |
| 其他節點返回驗證（midas/secret/summon/bounty 等） | `status_graph.json` 標記為 `historical_observed` 非 `verified` |

### 已知失敗 / 誤判紀錄

| 問題 | 紀錄依據 |
|---|---|
| 去重誤判：無盡試煉被跳過 | `daily_tasks_exploration.md`：裁切 200:1000 過寬，相似度 0.9098 被誤判為 duplicate |
| ADB 離線導致 STOPPED_FOR_HUMAN_REVIEW | `status_graph_observations.md`：第一次因 device offline 觸發 |
| endless_trial_route：battle_end 後進入 unknown 無限迴圈 | debug 截圖：`005_battle_end → unknown → unknown → unknown → 004_battle`（重新進入戰鬥！） |
| endless_trial_route：008_exit_confirm 卡住 | debug 截圖顯示連續 8 張 `008_exit_confirm`，顯示點擊 (589, 401) 未能關閉確認框 |
| endless_trial_route：006_battle_fail 後 unknown 迴圈 | `006_battle_fail → unknown → unknown → 004_battle`（又進去戰鬥）|
| 公會副本引導彈窗卡死 | `daily_tasks_exploration.md`：首次進入引導彈窗導致卡在 27 號精英據點 |
| midas_route：001_daily_tasks 任務已完成時仍重複 tap (839,400) | 今日實測：所有任務顯示「完成」，tap 意外觸發跳轉至競技場頁 |

---

## 6. 明顯不可靠或曾誤判的結果

1. **「去重」機制** — `is_duplicate_task()` 裁切範圍曾設定為 200:1000（過寬），導致「無盡試煉」被誤判為重複而跳過。已修改為 220:650，但**修復後尚未完整驗證**。

2. **battle_end 後的 unknown scene** — `005_battle_end` 辨識成功後，緊接著出現的畫面（可能是獎勵/升級提示遮罩）無法被任何 anchor 識別，導致：
   - `consecutive_unknown` 達到上限（>2 次）後 STOPPED
   - 或者在某些情況下繞回去重新點了戰鬥（`004_battle` 再出現）

3. **`008_exit_confirm` 座標 (589, 401) 失效** — debug 顯示連續 8 次識別到 exit_confirm 但點擊無效，確認框未關閉。座標可能偏移。

4. **`004_battle` 場景中 tap (902, 480) 的時機問題** — 場景辨識到戰鬥畫面後立即 tap，可能在戰鬥進行中誤點，而非點擊 "Start Battle" 按鈕。

5. **競技場 OCR（hash-map）** — `ocr_utils.py` 使用 MD5 hash 辨識數字字元，高度依賴渲染像素完全相同。字型 anti-aliasing、解析度微差都會造成 hash miss（回傳 -1）。無任何驗證紀錄。

6. **midas_route tap 座標 (839, 400) 不正確** — `navigation_graph.md` 記錄 Midas 前往按鈕為 (1399, 664)，但 run_midas.py 使用 (839, 400)，且未偵測任務是否已完成。

---

## 7. 目前最大的技術風險

### 風險 1：`endless_trial_route` 的 battle_end 後流程損壞（高）
`005_battle_end` 之後出現的「unknown」畫面目前無法處理：
- 目前 code：連續 >2 次 unknown → STOPPED
- 實際問題：某些情況下未 STOPPED，反而繞回 `004_battle`，**可能導致重複進入戰鬥**

### 風險 2：`008_exit_confirm` 點擊座標失效（高）
debug 清楚顯示 exit_confirm 場景被識別但 tap (589, 401) 無效，會陷入無限點擊迴圈。

### 風險 3：scene anchor 沒有 ROI 限制（中）
`run_endless_trial.py` 的 `get_roi()` 函數目前所有 roi_type 都 fallback 到 `full_screen`。這意味著 anchor 在全圖上比對，誤判風險更高。

### 風險 4：`004_battle` 戰鬥中 tap 邏輯不清（中）
`scene == "004_battle"` 時 `tap(902, 480)` 的意圖是點 "Start" 按鈕，但戰鬥進行中也會識別到此場景，導致在戰鬥中亂點。

### 風險 5：各 route 對「任務已完成」狀態無防護（中）
`run_midas.py` 實測證明：當每日任務已完成（按鈕為「完成」而非「前往」），腳本仍會盲目 tap，導致意外跳轉到其他頁面。

### 風險 6：OCR 使用 hash-map，非常脆弱（低-中）
`ocr_utils.py` 的 arena 戰力辨識方法在任何字型渲染差異下都會失敗，且沒有任何驗證結果可支撐其可靠性。

---

## 8. 接手建議

### 專案目前的真實狀態

- **底層工具（ADB + OpenCV + template matching）**：✅ 穩定，設計清楚
- **每日任務 probe**：✅ 基本可用，去重修復待驗證
- **無盡試煉 Vision-Guided（主線）**：🔄 架構完整，scene anchor 已建立，但 battle_end 後的流程有已知缺陷
- **競技場 route**：🔄 可以進入場景，但目標不清（是否需要 OCR 選對手？）
- **midas_route**：🔴 tap 座標錯誤，且無任務完成狀態防護
- **其他 routes（bounty/secret 等）**：🔴 只有空目錄骨架

### 哪些事情現在不應該動

- 不要動 `src/actions.py` 的 probe-daily-tasks（還沒驗證去重修復）
- 不要開始新的 route（arena OCR、廣告關閉等）
- 不要把 scratch 腳本當成正式功能

---

## 最小下一步（僅一個）

> [!IMPORTANT]
> **閱讀今日的 endless_trial_route debug 截圖，釐清 `005_battle_end` 之後到底發生了什麼，再決定是否需要修補。**

具體做法（純讀，不執行任何自動化）：

1. 打開 `experiments/endless_trial_route/debug/step_20260603_113315_005_battle_end.png` 確認戰鬥結算畫面長什麼樣
2. 打開緊接的 `step_20260603_113320_unknown.png`、`step_20260603_113323_unknown.png`、`step_20260603_113326_unknown.png` 確認是哪種畫面讓 scene detection 失敗
3. 判斷：是「結算畫面有遮罩擋住 anchor」、還是「anchor 裁切範圍不對」、還是「需要再等一秒才能拍到正確畫面」

**只有在看完截圖之後**，才能決定是：
- a) 新增一個 `005_post_battle_transition` anchor 來辨識那個過渡畫面
- b) 調整 `005_battle_end` 之後的 tap 座標
- c) 在 battle_end 後加一個固定等待時間

這是目前最小、最安全、最有明確答案的工作。
