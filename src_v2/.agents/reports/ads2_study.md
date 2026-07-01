# ADS2 深度研究報告

> 研究日期：2026-07-01
> 研究對象：`ads2/core/runner.py`（634 行）、`ads2/core/states.py`（179 行）、`ads2/core/context.py`、`ads2/core/profile.py`、`ads2/profiles/*.json`、`ads2/cli.py`

---

## 1. ReactiveRunner 狀態列表與主迴圈邏輯

`ReactiveRunner.run()` **不是**基於狀態機的架構，而是一個**單層 while True 迴圈**，在每次迭代內依序執行 5 個優先級掃描。`ads2/core/states.py` 是另立的 State Machine 架構，`ReactiveRunner` 目前**並未使用**它（見第 7 節）。

### 主迴圈每輪的 5 個優先級

| 優先級 | 目標 | threshold | ROI | 行為 |
|---|---|---|---|---|
| 1 | Profile finish_templates | JSON 指定（預設 0.85） | JSON 指定 | 命中即 break，結束 run() |
| 2 | free_ad_icons | 0.75 | 無 | tap 最多 10 次直到消失，sleep ad_wait 秒 |
| 3 | close_icons | 0.85 | 畫面上 40% | tap 最多 10 次直到消失 |
| 4 | got_icons | 0.70 | 無 | tap 最多 10 次直到消失 |
| 4b | Profile finish_templates（再確認） | 同上 | 同上 | 命中即 break |
| 5 | scene_anchors | 0.75 | 無 | 命中且 2.5s 後無 free_ad 則 break（完成） |

---

## 2. run() 完整流程步驟

```
ReactiveRunner.run()
├── setup()：ADB connect
├── 啟動 poll_esc daemon thread（每 50ms 偵測 ESC）
└── while True:
    ├── [0] 檢查 ESC → handle_esc_interact()
    ├── [1] _safe_screenshot()
    ├── [2] match_profile_finish(screen)  → 命中 break
    ├── [3] scan free_ad_icons(0.75)      → tap + sleep ad_wait
    ├── [4] scan close_icons(0.85, roi上40%) → tap
    ├── [5] scan got_icons(0.70)          → tap
    ├── [6] match_profile_finish(screen) 再確認 → 命中 break
    ├── [7] scan scene_anchors(0.75) → 2.5s 確認 → break（完成）
    ├── 全未命中 → sleep 0.5s
    ├── except AppRecoveryNeeded → recover_from_app_jump()
    └── except UserInterrupt → handle_esc_interact()
```

---

## 3. 所有 self.matcher.match_template 直接呼叫點

| 方法 | 行號 | asset 路徑 | ROI | threshold |
|---|---|---|---|---|
| `match_profile_finish()` debug | L312-318 | `condition.template_path`（profile JSON） | `condition.roi` | 0.0 |
| `match_profile_finish()` 正式 | L325-330 | `condition.template_path` | `condition.roi` | `condition.threshold` |
| `scan_category()` closure 內 | L358 | 各 category .png | 呼叫方給定 | 呼叫方給定 |
| 驗證 free_ad 消失 | L450 | `free_ad_match.template_path` | bbox ± 20px | 0.75 |
| 驗證 close 消失 | L493 | `close_match.template_path` | bbox ± 20px | 0.85 |
| 驗證 got 消失 | L538 | `got_match.template_path` | bbox ± 20px | 0.70 |
| `handle_esc_interact` 新圖測試 | L237 | `dest_path`（剛加入） | 無 | 0.1 |

---

## 4. `_image_cache` monkey-patch 完整實作

位置：`runner.py` L32-46，**module import 時立即執行**。

```python
_original_read_image = vm.read_image  # 保存原函式指標
_image_cache = {}                      # module 級 dict，永不清理

def cached_read_image(path, flags=cv2.IMREAD_UNCHANGED):
    try:
        mtime = path.stat().st_mtime   # 用 mtime 作為 cache key
    except:
        mtime = 0
    cache_key = (str(path), flags, mtime)
    if cache_key not in _image_cache:
        _image_cache[cache_key] = _original_read_image(path, flags)
    return _image_cache[cache_key]

vm.read_image = cached_read_image      # 全域替換，立即生效
```

**影響範圍**：同一 process 內所有經 `src.vision_matcher.read_image` 讀圖的路徑皆走快取。

**快取失效條件**：mtime 改變（檔案被覆寫）→ 自動重讀。

**無 restore 機制**：`_original_read_image` 已保存，但無對外提供 un-patch 介面。

---

## 5. keyboard 套件用途

### 觸發時機
1. **daemon thread**（`poll_esc`，L364-375）：每 50ms 輪詢 `keyboard.is_pressed('esc')`，觸發後設 `force_esc_trigger=True`
2. **主迴圈進入時**（L382）：直接檢查一次
3. **`sleep_or_esc()`**（L261）：所有 sleep 內每 100ms 檢查，觸發 `raise UserInterrupt`

### `handle_esc_interact()` 流程（L134-244）
1. 截圖存兩份至 `assets/2_communication/`（original + edit）
2. 開啟 mspaint 讓使用者用**藍色空心矩形**標示點擊目標
3. 關閉 mspaint 後用 `paint_cropper.find_blue_boxes + crop_inside_blue_box` 裁切藍框
4. 可選：白色去背（轉透明）
5. 使用者選擇類型（close_icons / got_icons / scene_anchors / free_ad_icons）
6. 自動編號存入對應目錄（`close_1.png`, `got_1.png`...）
7. 即時測試新特徵信心值（threshold=0.1）
8. 恢復主迴圈

---

## 6. profiles/ 目錄與 finish_templates

### 目錄結構
```
ads2/profiles/
├── call_of_the_gale.json
├── weekly_minigame.json
├── call_of_the_gale/         （profile 專用 assets）
└── templates/                （profile 通用 templates）
```

### call_of_the_gale.json

- `ad_wait`: 15

**finish_templates：**

| name | template | roi | threshold | description |
|---|---|---|---|---|
| `restore_3_darts_status` | `call_of_the_gale/restore_3_darts.png` | [520, 0, 150, 60] | 0.85 | 看完廣告後上方飛鏢資源列顯示已恢復 3 飛鏢 |

### weekly_minigame.json

- `ad_wait`: 15

**finish_templates：**

| name | template | roi | threshold |
|---|---|---|---|
| `weekly_minigame_finish` | `templates/weekly_minigame_finish.png` | [870, 460, 90, 40] | 0.85 |

> **路徑解析規則**（`profile.py _resolve_path`）：相對路徑先嘗試以 profile 所在目錄為 base，若不存在則 fallback 至 project root。

---

## 7. states.py 狀態機結構

> **重要**：`ReactiveRunner`（runner.py）目前並未引用或驅動 `states.py` 的任何狀態。這是兩套並存但互相獨立的架構。

### StateName Enum（`context.py` L17-26）

```python
class StateName(Enum):
    NAV_TO_HUB    = auto()   # 導航至大廳（無對應 State 實作）
    SWEEP_ADS     = auto()   # 掃描免費廣告
    TAP_FREE_AD   = auto()   # 點擊免費廣告
    INITIAL_WAIT  = auto()   # 初始等待廣告播放
    FIND_CLOSE    = auto()   # 尋找關閉按鈕
    TAP_CLOSE     = auto()   # 點擊關閉按鈕
    VERIFY_RETURN = auto()   # 驗證是否回到大廳
    DONE          = auto()   # 完成
    FAILED        = auto()   # 失敗
```

### State 轉移表

| State | Handler | 進入條件 | 下一 State |
|---|---|---|---|
| `SWEEP_ADS` | `SweepAdsState` | 入口 / 廣告完成後 | `TAP_FREE_AD`（有綠按鈕）/ `DONE`（無） |
| `TAP_FREE_AD` | `TapFreeAdState` | `last_match` 非空 | `INITIAL_WAIT` |
| `INITIAL_WAIT` | `InitialWaitState` | 進入廣告 | `FIND_CLOSE` |
| `FIND_CLOSE` | `FindCloseState` | 進入 | `TAP_CLOSE`（找到）/ `SWEEP_ADS`（已回廳）/ `FIND_CLOSE`（繼續等）|
| `TAP_CLOSE` | `TapCloseState` | 找到按鈕，tap_attempts < max | `VERIFY_RETURN` |
| `VERIFY_RETURN` | `VerifyReturnState` | 點完關閉 | `FIND_CLOSE`（按鈕仍在）/ `SWEEP_ADS`（已回廳 / 超時假設成功） |

### `_is_back_to_hub()` 錨點（`FindCloseState` L103 & `VerifyReturnState` L169）

三個 anchor 任一命中即確認回大廳：
- `scene_anchors/hub_anchor.png`
- `nav_icons/nav_kingdom.png`
- `scene_anchors/shop_anchor.png`
- threshold: `cfg.anchor_threshold`

---

## 8. cli.py Entry Point

### 入口
```bash
python ads2/cli.py run [args]
```

### 接受參數

| 參數 | 預設值 | 說明 |
|---|---|---|
| `--serial` | `emulator-5554` | ADB 設備 serial |
| `--ad-wait` | 15 | 點廣告後暫停秒數 |
| `--debug` | False（flag） | 開啟 debug 模式（儲存截圖） |
| `--profile` | None | 指定 profile 名稱（搜尋 `ads2/profiles/<name>.json`） |

> 若省略子命令（`args.command is None`），預設也執行 `run`。

---

## 9. 路徑 hardcode 分析

### `ReactiveRunner.__init__` 計算路徑（L61-75）

```
base_dir          = Path(__file__).parent.parent   → ads2/
assets_dir        = base_dir / "assets"
templates_dir     = assets_dir / "1_templates"    ← 目錄名固定
close_icons_dir   = templates_dir / "close_icons" ← 固定
got_icons_dir     = templates_dir / "got_icons"   ← 固定
free_ad_icons_dir = templates_dir / "free_ad_icons" ← 固定
scene_anchors_dir = templates_dir / "scene_anchors" ← 固定
manual_dir        = assets_dir / "2_manual_captures"
debug_errors_dir  = assets_dir / "debug_errors"
```

### `handle_esc_interact()` 內（L139）
```
comm_dir = base_dir / "assets" / "2_communication"  ← hardcode
```

### `profile.py`（L66）
```
ads2_dir / "profiles" / f"{path}.json"  ← 目錄名稱 "profiles" 固定
```

---

## 10. monkey-patch in-process 潛在影響

### 問題本質

`runner.py L46` 的 `vm.read_image = cached_read_image` 在 **module load 時立即執行**，任何 `import ads2.core.runner` 發生時（不需實例化），全域 patch 即生效。

### 在 adb_vl in-process 模式下的具體風險

| 風險 | 說明 |
|---|---|
| **所有 task 共享快取** | `src_v2/tasks/*.py` 的 `_wait_for()`/`_require()` 最終呼叫 `VisionMatcher.match_template`，底層讀圖走快取路徑 |
| **記憶體持續增長** | `_image_cache` 為 module-level dict，無 TTL、無容量上限 |
| **隱性 mtime 失效** | `debug_capture` 若覆寫同名檔案，mtime 改變觸發快取失效並重讀，對 task 來說是隱性行為 |
| **unittest 隔離破壞** | 只要 import `ads2.core.runner`，`vm.read_image` 被替換，影響所有 unittest 的 mock patch 預期 |
| **無法 un-patch** | `_original_read_image` 已保存，但無對外提供 restore 介面 |

### 建議（觀察，不動手，PM 確認後才執行）

將 patch 移至 `ReactiveRunner.__init__` 內按需執行，或改用 scope-local 包裝，避免全域污染。