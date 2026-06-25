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

