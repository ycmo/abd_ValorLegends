# src_v2 RD 開發規範

## 作用域（鐵律）

**可寫入的目錄：只有以下兩處，其他全部唯讀**
- `src_v2/`（含所有子目錄）
- `tests_v2/`（含所有子目錄）

**唯讀（任何情況下禁止修改）**：
`src/`、`tests/`、`ads2/`、`ads/`、`switch_account/`、`AwayFromKeyboard/`、
`call_of_the_gale/`、`magic_shop/`、`review/`、`utils/`、`.agents/`、
`assets/`、`tools/`、根目錄下所有 `.py` 和 `.md` 檔案。

違反作用域視為嚴重錯誤，PM 將退回整個交付。

---

## 架構核心概念

### 底層來自 src/，不複製

`src_v2/` 直接 import `src/` 的穩定層：

```python
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher, MatchResult, Roi
from src.config import TASK_SPECS, TAP_COOLDOWN_SECONDS, SHARED_ASSETS_DIR, TaskSpec
from src.exceptions import TaskFailedError, TaskSkippedError, BotError, MissingAssetError
from src.scene_detector import SceneDetector, Scene
from src.battle_handler import BattleHandler
from src.debug_log import DebugLogger
from src.daily_task_finder import DailyTaskFinder
from src.navigator import Navigator, OpenTaskStatus
```

不得把以上模組的代碼複製進 `src_v2/`。

### Task 的正確寫法

**禁止在任何 task 內自行實作 poll loop、截圖、模板匹配邏輯。**

task 只需寫：
- `spec`、`required_assets`、ROI 常數
- `execute()` 業務邏輯
- 需要時 override `execute_from_current_scene()` 或 `_pre_return_hook()`

所有等待/查找/點擊透過 `BaseTask` 提供的 API：

```python
self._wait_for(asset_name, *, roi, threshold, timeout_seconds)  # → Optional[MatchResult]
self._require(label, asset_name, *, roi, threshold, timeout_seconds)  # → MatchResult
self._tap(label, asset_name, *, roi, threshold, wait_after)  # → MatchResult
self._is_scene(scene)  # → bool
self._wait_for_scene(scene, timeout_seconds)  # → bool
self._log(message)
self._dismiss_overlay_by_blank_taps(...)
self._return_to_daily()  # 統一返回策略
```

### 裁切工具

參考 `.agents/crop_box_skill.md`。
裁切邏輯使用 `src.paint_cropper`，不在 task 或測試腳本中重寫 HSV 偵測。

---

## Debug 截圖規範

所有 debug 截圖透過 `src_v2.debug_capture.DebugCapture` 處理：
- 失敗截圖：`_require` 超時時自動儲存，檔名含 roi / conf / threshold
- action 截圖：`--debug-actions` 模式，每個 tap 前後各存一張
- cleanup：保留最新 5 個 session，舊的自動刪

task 內不得自行呼叫 `cv2.imwrite` 或建立截圖目錄。

---

## 測試規範

- 測試檔案放在 `tests_v2/`
- 使用 Python `unittest` + `unittest.mock`
- 禁止依賴真實 ADB、實機、網路、外部 API
- 禁止依賴本機 `assets/` 目錄是否存在（用 `patch.object` 隔離 asset 路徑）
- 每次交付前必須跑：

```
.venv\Scripts\python.exe -m pytest tests_v2/ -v
```

回報時貼完整輸出，不接受只說「已通過」。

---

## 交付格式

```
修改檔案：（正面列舉，只列 src_v2/ 和 tests_v2/ 底下的）
核心改動：（三句話以內）
測試結果：（pytest 完整輸出，必須顯示 X passed, 0 failed）
潛在風險：（誠實列出）
需實機驗證：（列出無法自動化的部分）
```
