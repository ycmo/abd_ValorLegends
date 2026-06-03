# Endless Trial Vision-Guided Route Runner MVP — Implementation Spec

## 1. 檔案結構 (File Structure)
將專案實作於獨立的資料夾模組，以利資源隔離與除錯：
```text
experiments/endless_trial_route/
├── run_endless_trial.py      # 主程式入口
├── README.md                 # 執行說明與實驗目標
├── assets/                   # 專屬圖片特徵庫
│   ├── anchors/              # 用於確認當前畫面的錨點圖片 (如標題、固定 UI)
│   └── buttons/              # 用於點擊的互動元素圖片
└── debug/                    # 失敗時的 overlay 截圖與 debug log 存放處
```

## 2. 完整 Template Asset 表 (Template Assets)
所有圖片特徵依據其重要性分為「必要(Required)」、「可選(Optional)」與「降級(Fallback)」。新增支援 Daily Tasks 入口所需的圖片特徵。

| Template 檔案名 | 目錄類別 | 重要性 | 用途說明 |
| :--- | :--- | :--- | :--- |
| `home_anchor` | anchors | **必要** | 確認處於主畫面/大廳 (如左上角頭像、右上任務鈕) |
| `bottom_wild_tab` | buttons | **必要** | 底部導覽列「野外」分頁按鈕 |
| `wild_page_anchor` | anchors | **必要** | 野外頁面的獨特標記 (防誤判，如野外頁籤高亮狀態) |
| `endless_trial_entry` | buttons | **必要** | 畫面中央偏下的無盡試煉城堡入口圖示 |
| `endless_trial_title` | anchors | **必要** | 進入無盡大廳後，左上角的「無盡試煉」標題 |
| `sub_dungeon_option` | buttons | **必要** | 可用的特定副本入口 (如：哀怨鐘樓字樣/圖案) |
| `stage_page_anchor` | anchors | **必要** | 關卡準備頁面的專屬特徵 (如關卡標題) |
| `challenge_button` | buttons | **必要** | 關卡頁面右下角的「挑戰」按鈕 |
| `confirm_yes` | buttons | **必要** | 彈窗確認時的「確定/是」按鈕 |
| `battle_end_indicator`| anchors | **必要** | 戰鬥結算特徵 (「勝利/失敗」字樣或「點擊空白處關閉」) |
| `daily_tasks_anchor` | anchors | **必要** | 判定處於每日任務頁 (如左上角「每日任務」標題) |
| `daily_task_endless_trial_row`| anchors | **必要** | 每日任務清單中「無盡試煉」該列的文字特徵或圖示 |
| `daily_task_go_button`| buttons | **必要** | 每日任務列專用的「前往/挑戰」按鈕 |
| `daily_tasks_return_anchor`| anchors | 可選 | 用於確認成功返回任務頁的依據 (預設可共用 `daily_tasks_anchor`) |

## 3. ROI 掃描區域定義 (Region of Interest)
為提升掃描速度與減少誤判，為不同的 template 指定專屬掃描區域 (ROI) 類型：

| ROI 類型 | 掃描範圍建議 (Y, X) | 適用 Template |
| :--- | :--- | :--- |
| `full_screen` | `[0:H, 0:W]` | `confirm_yes` |
| `bottom_nav` | `[H-150:H, 0:W]` | `bottom_wild_tab` |
| `center_map` | `[H*0.3:H*0.8, 0:W]` | `endless_trial_entry`, `sub_dungeon_option` |
| `top_title` | `[0:200, 0:W*0.6]` | `home_anchor`, `wild_page_anchor`, `endless_trial_title`, `stage_page_anchor`, `daily_tasks_anchor` |
| `task_list_area` | `[150:H-100, 0:W*0.7]` | `daily_task_endless_trial_row` (尋找目標任務列) |
| `dynamic_row_button` | `[row_y1:row_y2, W*0.7:W]` | **動態計算**：找到目標列後，限制在其 Y 軸範圍的右側區域掃描 `daily_task_go_button` |
| `bottom_right_button` | `[H*0.7:H, W*0.5:W]` | `challenge_button` |
| `battle_result_area` | `[H*0.2:H*0.8, 0:W]` | `battle_end_indicator` |

## 4. 具體 Route Steps 表 (Route Steps)
將流程解耦為五大階段：Entry Detection、Home Entry Route、Daily Tasks Entry Route、Shared Challenge Route、Return to Origin Route。每一步驟皆嚴格遵守：`pre_check -> target -> action -> post_check` 的流程。

### Phase 1: Entry Detection Steps
腳本開始先截圖，判斷目前所處畫面。無法判斷則視為未知狀態。

| step_id | expected_screen | target anchor | action | 判斷之 entry_context | failure behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0_detect_daily` | 任意 | `daily_tasks_anchor` | *(None)* | `daily_tasks` | 嘗試下一判定 |
| `0_detect_home` | 任意 | `home_anchor` | *(None)* | `home` | 嘗試下一判定 |
| `0_detect_wild` | 任意 | `wild_page_anchor` | *(None)* | `wild` | 嘗試下一判定 |
| `0_detect_endless`| 任意 | `endless_trial_title`| *(None)* | `endless_trial` | 嘗試下一判定 |
| `0_detect_fail` | 未知 | *(None)* | *(None)* | *(None)* | STOPPED_FOR_HUMAN_REVIEW |

### Phase 2: Route A (Home Entry Route)
若 `entry_context == home` 或 `wild` 則進入此路徑（wild 則跳過 goto_wild）。

| step_id | expected_screen | pre_check anchor | target template (fallback) | action | post_check anchor | timeout | retry | failure behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1A_goto_wild` | 主畫面/掛機頁 | `home_anchor` | `bottom_wild_tab` (座標) | tap | `wild_page_anchor` | 5s | 2 | STOP & Dump |
| `2A_enter_endless`| 野外頁 | `wild_page_anchor`| `endless_trial_entry` | tap | `endless_trial_title` | 5s | 2 | STOP & Dump |

### Phase 3: Route B (Daily Tasks Entry Route)
若 `entry_context == daily_tasks` 則進入此路徑。

| step_id | expected_screen | pre_check anchor | target template | action | post_check anchor | timeout | retry | failure behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1B_find_row` | 每日任務頁 | `daily_tasks_anchor`| `daily_task_endless_trial_row`| *(None)* | 取得動態 ROI | 5s | 1 | 找不到視為任務已解, return |
| `2B_click_go` | 每日任務頁 | *(row 已鎖定)* | `daily_task_go_button` | tap | `endless_trial_title` 或 `stage_page_anchor` | 5s | 2 | STOP & Dump |

*(註：如果 B 路線點擊後直接進入了 `stage_page_anchor`，後續的 `3_select_dungeon` 會藉由 pre_check 發現已經在關卡準備頁而自動略過。)*

### Phase 4: Shared Challenge Route
不論 Route A 或 B，統一收束至此流程。

| step_id | expected_screen | pre_check anchor | target template (fallback) | action | post_check anchor | timeout | retry | failure behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `3_select_dungeon`| 無盡大廳 | `endless_trial_title` | `sub_dungeon_option` | tap | `stage_page_anchor` | 5s | 2 | STOP & Dump |
| `4_start_challenge`| 關卡頁 | `stage_page_anchor` | `challenge_button` | tap | *(戰鬥中)* | 3s | 1 | STOP & Dump |
| `5_wait_battle` | 戰鬥畫面 | *(無)* | `battle_end_indicator` | wait | `battle_end_indicator` 浮現 | 60s | 0 | STOP & Dump (卡死) |
| `6_close_result` | 結算頁面 | `battle_end_indicator` | 點擊空白處中心 | tap | 回到上一層 (看情境) | 5s | 3 | STOP & Dump |

### Phase 5: Return to Origin Route
根據初始偵測到的 `entry_context` 決定返回成功條件。

| entry_context | return_target_anchor | 未知/無法回家的行為定義 |
| :--- | :--- | :--- |
| `daily_tasks` | `daily_tasks_anchor` | 返回 4 次未見 `daily_tasks_anchor` 則 STOP & Dump |
| `home` | `home_anchor` | 返回 4 次未見 `home_anchor` 則 STOP & Dump |
| `wild` | `wild_page_anchor` | 返回 4 次未見 `wild_page_anchor` 則 STOP & Dump |
| `endless_trial` | *(就地結束)* | 不需返回，結算關閉後腳本即視為完成任務 |

## 5. Return to Origin 具體設計 (Return to Origin Specification)
具備明確的狀態機防呆邏輯：
* **最大 Back 次數**：最多嘗試 **4 次**。
* **等待間隔**：每次觸發返回（Back鍵 或 左上固定返回座標）後，固定 **等待 2.0 秒**。
* **成功判定**：等待後，擷取畫面並使用 ROI=`top_title` 掃描對應的 `return_target_anchor`。若 Confidence $\ge 0.85$，立即判定成功並 return。
* **失敗行為**：若 4 次嘗試後依然掃不到 `return_target_anchor`，馬上 Dump 當前畫面 Screenshot 到 `experiments/endless_trial_route/debug/`，然後拋出例外並 `STOPPED_FOR_HUMAN_REVIEW`。

## 6. Benchmark Log 格式 (Benchmark Log Format)
每一步驟都輸出標準化 JSON 格式供稽核：
```json
{
  "current_step": "3_select_dungeon",
  "expected_screen": "無盡大廳",
  "screenshot_ms": 120,
  "match_ms": 45,
  "matched_template": "assets/buttons/sub_dungeon_option.png",
  "confidence": 0.925,
  "bbox": [200, 300, 400, 400],
  "center": [300, 350],
  "action_taken": "tap",
  "total_step_ms": 350
}
```

## 7. 失敗策略 (Failure Strategy)
找不到 template 或遇到預期外狀態時的最高準則：
- **不亂點**：嚴禁退化至盲目點擊或亂嘗試點擊畫面各處。
- **不無限 Retry**：嚴格遵守 Step 表格的 `retry limit`，超次即結束。
- **不重啟遊戲**：不實作或呼叫遊戲的 crash 重啟邏輯。
- **Dump Debug**：將當前截圖存入 `debug/` 資料夾，檔名標記時間戳記與失敗 step_id。
- **停止流程**：印出 `STOPPED_FOR_HUMAN_REVIEW`，流程拋出異常或以 Exit Code 1 結束 Python 行程，交由人工介入處理。

## 8. 實作邊界重申 (Implementation Boundaries)
在接下來的開發階段，**不會**實作：
* 整合進 `src/main.py` 或 `src/actions.py` 的 main flow。
* 碰觸或引入 `ad closer` 機制。
* 開發成一個泛用的 daily task bot 架構。
* 開發通用 DSL 解析器 (YAML/JSON 等語法轉成自動化動作)。
* 使用 OCR 辨識、YOLO 物件偵測、撰寫 GUI 工具，或建立多設備並行框架。
* 修改網路封包、讀取/寫入記憶體、修改/注入 APK 等外掛行為。

## G. 驗收方式 (Acceptance Criteria)
1. **目錄隔離**：可清楚看到 `experiments/endless_trial_route` 資料夾，且 `run_endless_trial.py` 可單獨執行。
2. **符合 Log**：執行終端機與紀錄檔必須完美吐出符合第 6 點格式的 JSON 數據。
3. **動態 ROI 尋找前往**：在 Daily Tasks 路徑中，必須先找出文字 row，且只在該列的 Y 軸範圍尋找「前往」按鈕。
4. **上下文返鄉 (Context-Aware Return)**：腳本能正確記憶起點，若從任務頁出發必定返回任務頁；從主頁出發必定返回主頁。

## H. 實作時最容易失敗的 5 個點 (Top 5 Risk Points)
1. **動態 ROI 切割錯誤**：在 Daily Tasks 列表尋找無盡試煉列後，若 Y 軸範圍切割不精準 (太窄或太寬)，會導致找不到或誤點其他任務的「前往」按鈕。
2. **Daily Task 狀態混亂**：任務已被領取、已完成或正在列表最下方需要滾動，這份 MVP 未處理滾動邏輯，可能直接 return 失敗。
3. **過場動畫干擾**：跳轉畫面時的漸變效果 (Fade-in/out) 或過場動畫過長，導致 pre_check 在動畫播放期間提早進行並失敗。
4. **戰鬥結算重疊干擾**：勝利/失敗頁面若出現額外的成就解鎖、升級提示或獲得獎勵遮罩，會遮擋預期的 `battle_end_indicator`。
5. **Return to Origin 遭遇彈窗**：多次 back 時，可能觸發如「確認要放棄挑戰嗎？」的彈窗，單純的 back 操作會無效，需要額外偵測確認對話框。
