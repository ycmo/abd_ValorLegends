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

## Validation

修改裁框邏輯後至少執行：

```powershell
.\.venv-codex\Scripts\python.exe -m unittest tests.test_paint_cropper
```

若改動影響 screenshot/manual crop workflow，還需執行：

```powershell
.\.venv-codex\Scripts\python.exe -m unittest tests.test_manual_screenshots
```

