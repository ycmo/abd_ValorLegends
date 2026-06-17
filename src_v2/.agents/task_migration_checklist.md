# Task 移植 Checklist

每個 task 從舊版（`src/tasks/`）移植到 `src_v2/tasks/` 時，使用此 checklist 逐項確認。

## 移植前（Study 階段）

- [ ] 讀完舊版 task 全文
- [ ] 列出舊版 task 的所有 `_match_task_asset` / `_require_task_asset` / `_tap_task_asset` 呼叫點
- [ ] 確認 ROI 常數和 threshold 值（直接搬，不改）
- [ ] 確認是否有 `execute_from_current_scene()` override
- [ ] 確認是否有特殊返回路徑（需要 `_pre_return_hook()`）
- [ ] 確認是否有 OCR 依賴（arena、time_travel、summon）
- [ ] 確認是否有 busy overlay 依賴（midas）

## 移植時（實作規則）

- [ ] 不在新版 task 內實作任何 poll loop
- [ ] 不在新版 task 內定義 `_match_task_asset` / `_require_task_asset` / `_tap_task_asset`
- [ ] 全部改用 `self._wait_for()` / `self._require()` / `self._tap()`
- [ ] ROI 常數完整複製（不改值）
- [ ] `task_scene_anchors` 完整複製
- [ ] `required_assets` 完整複製
- [ ] 在 `tasks/__init__.py` 的 `TASK_CLASSES` 新增登記

## 移植後（驗收）

- [ ] `pytest tests_v2/ -v` 全部通過
- [ ] `python -c "from src_v2.tasks import TASK_CLASSES; print(TASK_CLASSES)"` 能看到新 task
- [ ] 新版行數 < 舊版行數（boilerplate 有被消滅）

## 各 Task 移植優先順序

| 優先 | Task | 複雜度 | 特殊依賴 |
|------|------|--------|---------|
| Phase 1 ✅ | guild_wish | 低 | 無 |
| Phase 2 | secret_realm | 低 | 無 |
| Phase 2 | summon | 中 | OCR（page label）|
| Phase 2 | time_travel | 中 | OCR（gem cost）|
| Phase 2 | midas | 中 | busy overlay |
| Phase 3 | arena | 高 | OCR + checkbox HSV |
| Phase 3 | endless_trial | 高 | state machine |
| Phase 3 | bounty | 待確認 | stub |
| Phase 3 | campaign | 待確認 | stub |
| Phase 3 | guild_dungeon | 待確認 | stub |
| Phase 3 | magic_shop | 待確認 | stub |
