# Endless Trial Vision-Guided Route Runner MVP

此為無盡試煉（Endless Trial）的 vision-guided 獨立支線實驗。此模組作為 MVP，旨在驗證「純依賴畫面辨識」完成一次無盡試煉挑戰的可行性，並取代硬編碼座標點擊策略。

## 特色
1. **Context-Aware Entry**：腳本啟動時會透過截圖自動判斷目前所處於主城 (`home`)、野外 (`wild`) 或是每日任務頁 (`daily_tasks`)。
2. **動態 ROI**：在每日任務頁面中，會先辨識「無盡試煉」任務列的垂直區間 (Y 軸)，並限制僅在該區間的右側尋找「前往」按鈕，避免誤點。
3. **Fail-Fast**：在找不到特徵時，不會盲目亂點也不會無限重試，而是立即儲存 debug screenshot 並以 `Exit Code 1` 終止程式 (`STOPPED_FOR_HUMAN_REVIEW`)。
4. **Benchmark Logging**：每一步驟都會輸出標準的 JSON log，方便追蹤辨識耗時、信心值 (confidence)、特徵座標等資訊。

## 執行方式
```bash
# 確保在專案根目錄下執行 (或是能讀取到 assets/ 的位置)
python experiments/endless_trial_route/run_endless_trial.py --serial 127.0.0.1:5555 --debug
```

### 可用參數：
* `--serial`：ADB 設備的 Serial (預設 `127.0.0.1:5555`)
* `--threshold`：Template 匹配的最低信心值 (預設 `0.82`)
* `--timeout`：戰鬥結束監聽的最長等待時間 (預設 `90`)
* `--interval`：連續點擊/動作的間隔秒數 (預設 `1.0`)
* `--debug`：開啟 debug 功能

## Template 放置方式
請將截圖並裁切好的 PNG 模板放在對應的目錄中：
* `assets/anchors/`：放置用於確認狀態的靜態特徵（如標題、介面標籤）。
* `assets/buttons/`：放置用於點擊的動態特徵（按鈕、副本入口）。

## 如何測試 Missing Template
刪除或更名 `assets/` 中的任何一個必要模板，執行腳本。腳本應在初始化階段立即列出缺少的檔案，然後安全退出 (不拋出 Exception stack trace)。

## 如何測試不同路線
1. **Daily Tasks Route**：手動開啟遊戲的「每日任務」列表，將無盡試煉列出現在畫面上，然後執行腳本。
2. **Home Route**：手動回到遊戲主畫面（掛機畫面），執行腳本。

## 成功與失敗判定
* **成功**：當腳本辨識到 `battle_end_indicator.png` 時，終端機會印出 `DONE` 並結束。
* **失敗**：任何一步驟超過重試次數，會將帶有時間戳記的當下截圖寫入 `debug/` 目錄，印出 `STOPPED_FOR_HUMAN_REVIEW` 並以錯誤碼 1 結束。
