# Crop Box Skill

此專案的人工標框裁切必須使用共用工具，不要在任務腳本或臨時分析中重新撰寫 OpenCV 顏色偵測邏輯。

## Box Color Convention

- 藍框：正式 template 候選圖。
  - 用於任務標籤、按鈕、可重複使用的模板。
  - 裁切時應移除框線，只保留框內內容。
- 紅框：點擊區域。
  - 用於標出 tap/click 位置或可點擊區域。
  - 若實作需要暫時 template，可以用紅框裁切，但檔名或註解需標明其主要用途是點擊。
- 綠框：辨識 anchor。
  - 用於畫面狀態判斷、ROI anchor、scene recognition。
  - 應優先裁穩定且不易變動的 UI 區塊。

## Required APIs

使用 `src.paint_cropper`：

```python
from src.paint_cropper import (
    find_blue_boxes,
    find_red_boxes,
    find_green_boxes,
    crop_inside_colored_box,
)
```

不得自行重寫 HSV/BGR 閾值、contour 篩選、去框線裁切、去重邏輯。若偵測不穩，應改進 `src.paint_cropper` 並補 `tests/test_paint_cropper.py`。

## Static Template Crops

若 manual screenshot 已經畫了紅框、藍框、綠框，正式 template 不應直接手裁框線圖。

優先做法：

1. 從 `captures/action_debug/` 或 `log/*_run_all/` 找同一個 UI 狀態的未標框截圖。
2. 用固定 ROI 靜態裁出乾淨 template，存到 `assets/tasks/<task_key>/` 或 `assets/shared/`。
3. 立刻用真實截圖驗證信心值，並在回覆中記錄 confidence。
4. 任務程式優先使用 template，比不到時才使用 shared asset 或固定點擊 fallback。

正式資產檢查：

- crop 內不得含有可見的紅/藍/綠 Paint 框線。
- `required_assets` 只能列出程式實際會用到的資產。
- debug action 應標出匹配 bbox 與點擊位置，方便使用者 review。

## Validation

修改裁框邏輯後至少執行：

```powershell
.\.venv-codex\Scripts\python.exe -m unittest tests.test_paint_cropper
```

若改動影響 screenshot/manual crop workflow，還需執行：

```powershell
.\.venv-codex\Scripts\python.exe -m unittest tests.test_manual_screenshots
```
