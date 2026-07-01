# AwayFromKeyboard

## 點金手自動循環

`loop_toggle_midas.py` 預設就是自動循環模式，不再需要 `--auto`。

兩帳號循環：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py
```

四帳號循環：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --all
```

第一輪先掃完整帳號，再回 `em3` 點金、讀冷卻並睡眠：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --all --sweep-first
```

保留操作前後截圖，方便確認點擊與路由：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --all --sweep-first --debug-actions
```

Discord 狀態通知預設開啟。只需要關閉通知時加：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --no-discord
```

## Sweep-first 第一輪順序

`--sweep-first --all` 會依起始帳號調整第一輪順序，減少 Google/email 帳號來回切換：

```text
em3   -> 311 -> tiger -> 14  -> em3
311   -> tiger -> 14 -> em3
tiger -> 14 -> 311 -> em3
14    -> tiger -> 311 -> em3
```

最後的 `em3` 會執行點金手 auto 判斷：能點就點，不能點就 OCR 讀冷卻時間並進入大休眠。

## 點金手路由規則

點金手由 AFK route 進場，不走每日任務列表。這可以避免每日任務已完成後標籤變灰或消失，導致找不到點金手。

相關設定：

- route 圖片：`AwayFromKeyboard/route_screenshots/點金手/`
- 任務執行：直接呼叫 `MidasTask.execute_auto()`，不讀 `afk_tasks.ini`
- 偵錯截圖：加 `--debug-actions` 後輸出到 `captures/action_debug/`

## loop_afk 每日完成紀錄

`loop_afk.py` 會記錄當天每個帳號已完成的 route。已完成的帳號/route 不會重複執行；如果某個帳號今天所有 route 都完成，也不會特地切換過去。

```powershell
python.exe AwayFromKeyboard\loop_afk.py --debug-actions
```

指定不同任務設定檔：

```powershell
python.exe AwayFromKeyboard\loop_afk.py --ini AwayFromKeyboard\afk_tasks_event.ini --debug-actions
```

`--config` 和 `--ini` 等價。指定 ini 會同時套用到 `loop_afk.py` 和它呼叫的 `run_router.py` 子程序。

ini 可以指定啟動時間；未指定 `--now`、`--delay` 或 `--du8` 時，程式會等到這個時間才開始執行：

```ini
[settings]
start_time = 08:10:00

[每日任務]
enable = Y
command = -m src.main --debug run-all
```

要臨時忽略 ini 的 `start_time` 並立刻執行：

```powershell
python.exe AwayFromKeyboard\loop_afk.py --now --debug-actions
```

等待優先順序是：`--now` 立刻執行最高；其次是命令列的 `--du8` / `--delay`；最後才使用 ini 的 `start_time`。

Discord 狀態通知預設開啟，會回報帳號切換與 route 開始/完成。只需要關閉通知時加：

```powershell
python.exe AwayFromKeyboard\loop_afk.py --no-discord
```

完成紀錄依遊戲重置日建立，切換點是台灣時間早上 08:00。08:00 前仍算前一天：

```text
AwayFromKeyboard/state/route_completion_YYYY-MM-DD.json
```

需要忽略今日紀錄、強制全部重跑時：

```powershell
python.exe AwayFromKeyboard\loop_afk.py -f --debug-actions
```

需要等到早上 8 點後再多等一段時間，例如活動常晚 10 分鐘開：

```powershell
python.exe AwayFromKeyboard\loop_afk.py --du8 --delay 00:10:00 --debug-actions
```

`--skip-current` 已移除；現在由每日完成紀錄決定是否跳過目前帳號。

## Router 框線規則

route 截圖中的框線會決定 Router 行為：

- 紅框：點擊目標，點擊紅框中心。
- 綠框：Anchor，只確認目標出現，不點擊。

檔名 suffix：

- `_optional`：找不到時略過。
- `_verify`：點擊後確認自己消失，未消失會重點。
- `_verifyNext`：點擊後確認下一個排序步驟出現，未出現會重點。

範例：

```text
01主畫面點擊野外_verifyNext.png
02確認進入野外.png
```

`01` 點完後會等待 `02` 的 template 出現；如果等不到，會回頭重點 `01`。`02` 可以是紅框或綠框，常見用法是綠框 Anchor。
