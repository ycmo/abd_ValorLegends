# src_v2 終態架構設計（定稿）

## 設計原則
`src_v2` 完全自給自足。`src/` 只被讀取（底層工具：adb_controller、vision_matcher），不被修改。
共用的部分只 maintain 一份，所有 task 通過 `src_v2` 的共用層呼叫。

---

## 最終目錄結構

```
src_v2/
  main.py                    # CLI 入口：run-task / run-all / run-current-scene-task
  config.py                  # 合併版 TASK_SPECS（src + v2 新增）
  task_runner.py             # BaseTask / DailyRunner / TaskRunResult
  debug_capture.py           # 統一 debug 截圖
  scene_navigator.py         # 導航輔助層
  tasks/
    __init__.py              # TASK_CLASSES registry
    # Daily Tasks
    guild_wish.py  secret_realm.py  summon.py  time_travel.py
    midas.py  endless_trial.py  arena.py  guild_dungeon.py
    bounty.py  campaign.py  magic_shop.py
    # Independent Tasks
    abyss.py             # from src/tasks/abyss.py
    hero_contest.py      # from src/tasks/hero_contest.py
    call_of_the_gale.py  # from call_of_the_gale/scripts/
    ads.py               # AdsTask(BaseTask)，殼，呼叫 src_v2/ads/runner.py
  ads/                       # ads 獨立子套件（原 ads2/core/）
    __init__.py
    runner.py            # ReactiveRunner，不 monkey-patch，image cache 本地化
    profile.py           # AdsProfile / load_ads_profile（保留機制）
    self_heal.py         # mspaint 標框工具（開發維護，不進 execute()）
  afk/                       # AFK 調度層（Phase 5）
    __init__.py
    loop.py              # from AwayFromKeyboard/loop_afk.py
    router.py            # from AwayFromKeyboard/integration_task/
    task_config.py       # .ini 解析
    ui_recovery.py       # UI 異常復原

assets/
  tasks/                     # 所有 task template（已有結構）
    guild_wish/  arena/  ...
    abyss/  hero_contest/    # 已有
    ads/                     # 從 ads2/assets/1_templates/ 搬過來
    call_of_the_gale/        # 從 call_of_the_gale/assets/ 搬過來
  routes/                    # AFK 路由導航截圖（從 AwayFromKeyboard/route_screenshots/）
    深淵/  點金手/  ...       # 會持續增加

captures/                    # 統一 debug 截圖出口（已有）
```

---

## ads 子套件架構決策

`src_v2/ads/` 是獨立子套件，不是普通 task：

```
呼叫鏈：
  src_v2.main run-task ads [--profile weekly_minigame]
    → AdsTask(BaseTask).execute(profile=...)
      → src_v2.ads.runner.ReactiveRunner(context, profile)
        → src_v2.ads.profile.load_ads_profile(profile_name)
        → 主迴圈（使用 context.controller / context.matcher，不建新的）

開發工具（不在 execute() 路徑內）：
  src_v2.ads.self_heal  ← 按 ESC 觸發，mspaint 標框，產生新 template
```

**移除 monkey-patch**：`vm.read_image = cached_read_image` 改為在 `ReactiveRunner` 內部維護一個 instance-level image cache dict，不污染全域。

**`2_communication/`**（自癒系統工作目錄）→ 保留在 `ads2/` 原位或移到 `src_v2/ads/communication/`，由 `self_heal.py` 負責管理，不納入 `assets/tasks/`。

---

## 工作優先序

### Phase 4（進行中）—— Task 移植
1. `src_v2/config.py` 建立（含 call_of_the_gale / ads 的 TaskSpec）
2. `hero_contest` 移植
3. `abyss` 移植（1443 行，最重）
4. `call_of_the_gale` 移植
5. `src_v2/ads/` 建立 + `ads.py` AdsTask

### Phase 5 —— Cut-over
6. `src_v2/main.py` CLI 入口
7. `src_v2/afk/` AFK 調度整合
8. `assets/routes/` 建立（搬 route_screenshots）
9. `afk_tasks.ini` 全部改 `-m src_v2.main`

---

## 原則：不 maintain 多份

| 現況（多份） | 終態（單一） |
|-------------|-------------|
| `ads2/core/runner.py` + `ads2/core/profile.py` | `src_v2/ads/runner.py` + `src_v2/ads/profile.py` |
| `ads2/assets/1_templates/` | `assets/tasks/ads/` |
| `AwayFromKeyboard/loop_afk.py` | `src_v2/afk/loop.py` |
| `AwayFromKeyboard/route_screenshots/` | `assets/routes/` |
| 各模組自己建 DeviceController | 全部走 `build_context()` 的 `context.controller` |
