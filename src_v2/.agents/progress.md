# Phase 進度追蹤

## Phase 1 — 骨架驗證 ✅ 完成

目標：`BaseTask` 架構 + `guild_wish` 跑通 + 測試全綠

| 項目 | 狀態 |
|------|------|
| `src_v2/task_runner.py`（BaseTask + build_context） | ✅ 完成 |
| `src_v2/debug_capture.py`（輕量版） | ✅ 完成 |
| `src_v2/tasks/guild_wish.py` | ✅ 完成 |
| `src_v2/daily_runner.py` | ✅ 完成 |
| `tests_v2/test_task_runner.py` | ✅ 30 passed, 0 failed |

**Approve 紀錄**：
- `save_failure()` 回傳型別改為 `Optional[Path]`，`None` 代表未儲存
- `_return_to_daily()` 順序修正：先判斷場景再呼叫 hook
- 測試以 `patch.object` 隔離本機 asset 路徑，不依賴實體 assets/

---

## Phase 2 — 批量移植 ✅ 完成

目標：移植 4 個中複雜度 task

| 項目 | 狀態 |
|------|------|
| `src_v2/tasks/secret_realm.py` | ✅ 32 tests |
| `src_v2/tasks/summon.py` | ✅ 36 tests |
| `src_v2/tasks/time_travel.py` | ✅ 40 tests |
| `src_v2/tasks/midas.py` | ✅ 45 tests |

**累計**：5 個 task 移植完成，45 passed, 0 failed

---

## Phase 3 — 高複雜度 task + 獨立模組整合

目標：移植剩餘 task + 整合獨立模組

| 項目 | 狀態 |
|------|------|
| `src_v2/tasks/arena.py` | 🔲 未開始 |
| `src_v2/tasks/endless_trial.py` | 🔲 未開始 |
| `src_v2/tasks/bounty.py` | 🔲 未開始 |
| `src_v2/tasks/campaign.py` | 🔲 未開始 |
| `src_v2/tasks/guild_dungeon.py` | 🔲 未開始 |
| `src_v2/tasks/magic_shop.py` | 🔲 未開始 |
| `AwayFromKeyboard/` 整合規劃 | 🔲 未開始 |
| `ads2/` 整合規劃 | 🔲 未開始 |
| `call_of_the_gale/` 整合規劃 | 🔲 未開始 |
| `switch_account/` 整合規劃 | 🔲 未開始 |

---

## Cut-over 條件（src_v2 升格為 src）

- [ ] 所有 11 個 daily task 移植完成
- [ ] `pytest tests_v2/ -v` 全部通過
- [ ] 實機跑完整 `run-tested-daily` 至少一次
- [ ] `src_v2/main.py` 可執行所有原 `src/main.py` 的子命令
