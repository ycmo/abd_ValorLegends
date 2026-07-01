# Call of the Gale 實作報告

## 修改摘要
1. 建立 `src_v2/tasks/call_of_the_gale.py`，完整移植 `auto_shoot.py` 與 `single_shoot.py` 的業務邏輯。
   - 將原本 `argparse` 與 `sys.exit()` 的獨立腳本形式，改寫為 `BaseTask` 的 `execute()` 流程。正常完成或無卷軸時改為 `return` 退場，異常時 `raise TaskFailedError`。
   - 移除自建的 `DeviceController` 與 `VisionMatcher`，全部改用 `self.context.controller` 和 `self.context.matcher`。
   - 重用既有的 OCR 與影像辨識函式，新增 `_get_ocr_reader` 方法回傳 `get_cached_easyocr_reader` 供測試時 `mock` 攔截，以避免下載模型。
   - 重寫 `ads2` 免費廣告續命功能，改為 `import` `AdsReactiveRunner`。
   - 由於這是不同於 VL 的獨立遊戲，因此設定 `task_scene_anchors = ()` 並覆寫 `_execute_and_return` 方法，結束時不再呼叫 `_return_to_daily()`，以保持原汁原味的狀態退出。
2. 於 `src_v2/tasks/__init__.py` 中註冊 `"call_of_the_gale": CallOfTheGaleTask`。
3. 於 `tests_v2/test_task_runner.py` 中新增 `TestCallOfTheGaleExecute` 測試群組：
   - `test_execute_exits_when_scrolls_zero`：當卷軸為 0 時，正常 `return` 而非 `sys.exit`。
   - `test_execute_runs_one_round_then_exits`：模擬迴圈完成一回合並順利辨識退出按鈕的流程。
   - `test_execute_and_return_does_not_call_return_to_daily`：驗證 `_execute_and_return` 不會誤觸發 `_return_to_daily` 導致非預期動作。

## pytest 結果
`64 passed in 29.10s`
