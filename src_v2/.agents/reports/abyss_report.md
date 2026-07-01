# AbyssTask 實作報告

## 修改摘要
1. 建立 `src_v2/tasks/abyss.py`，完整移植 1443 行的原版 AbyssTask 邏輯，並對應 `src_v2` 架構進行調整：
   - 移除舊版 `_log` override，改用繼承的方法。
   - 將原有的 `run()` 改名為 `execute()`，保留所有既有例外拋出與流程（如提早結束時拋出 `TaskSkippedError`）。
   - Override `_execute_and_return` 方法，因 Abyss 為獨立任務，不會呼叫 `_return_to_daily()`，而是直接結束並回傳 `TaskRunResult(state=TaskState.COMPLETED)`。
   - 全部保留自定義的 `self.context.matcher.match_template` 呼叫與 `probe_rental_scan` 中的 DebugCapture（開發用）資料夾邏輯。
2. 於 `src_v2/tasks/__init__.py` 註冊 `abyss`: `AbyssTask`。
3. 於 `tests_v2/test_task_runner.py` 新增 `TestAbyssExecute` 測試群組：
   - `test_execute_skips_when_done_zero`：驗證挑戰耗盡時正確拋出 skip。
   - `test_execute_returns_completed_when_all_steps_succeed`：透過模擬完整的戰鬥流程與模擬 OCR Reader 防止網路下載，驗證正常通過。
   - `test_execute_and_return_does_not_call_return_to_daily`：驗證不會觸發返回 daily tasks 的邏輯。

## pytest 結果
`61 passed in 6.91s`
