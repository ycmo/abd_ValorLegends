# Valor Legends ADB 自動化

這是重構後的新主線。專案只做外部 UI 自動化：

```text
ADB 截圖 -> OpenCV template matching / OCR -> ADB tap/swipe
```

不做封包攔截、記憶體修改、APK 注入。

## 目前決策

- 以 `docs/project_analysis.v1.md` 為準。
- Codex 交接與工作筆記記錄在 `CODEX_NOTES.md`。
- 實機測試發現與臨時結論記錄在 `docs/implementation_notes.md`。
- 待使用者確認的需求問題記錄在 `docs/requirements_QA.md`。
- 初期只支援 960x540 截圖解析度；不符合就停止。
- `manual_screenshots/` 是使用者提供的真相來源，不覆蓋。
- Codex 自行截圖放 `captures/` 或 `assets/raw_captures/`。
- 舊架構已封存到 `legacy/20260604_pre_rewrite/`。
- 看廣告相關內容放 `ads/`，不混進每日任務主線。
- 第一版不自動點每日任務「領取」。

## 安裝

```powershell
pip install -r requirements.txt
```

## 常用指令

建議從專案根目錄執行：

```powershell
python -m src.main devices
python -m src.main check-device
python -m src.main screenshot
python -m src.main detect-scene
python -m src.main list-tasks
python -m src.main run-task midas
python -m src.main run-all
```

目前預設 ADB serial 是 `emulator-5554`。如果 BlueStacks 之後又變回 `127.0.0.1:5555`，可以用任一方式覆蓋：

```powershell
python -m src.main --serial 127.0.0.1:5555 check-device
$env:VL_ADB_SERIAL = "127.0.0.1:5555"
```

手動截圖工具保留原本用途：

```powershell
python -m src.manual_screenshots --task 無盡試煉 --index 1 --scene 每日任務
```

## 新目錄

```text
src/
  adb_controller.py       ADB 連線、截圖、tap/swipe/back
  vision_matcher.py       OpenCV template matching
  scene_detector.py       共用場景辨識
  daily_task_finder.py    每日任務列表找任務與前往按鈕
  navigator.py            回每日任務、開任務
  battle_handler.py       戰鬥等待與結果處理
  task_runner.py          任務基底與 step runner
  daily_runner.py         單任務/全任務執行器
  tasks/                  各每日任務

assets/
  shared/                 共用 template
  tasks/<task_key>/       任務專用 template
  raw_captures/           Codex 擷取的原始素材

ads/                      Antigravity 看廣告工作區
legacy/                   舊檔封存，本地保留、不納入 git
```

## Template 命名

每條任務至少需要：

```text
assets/tasks/<task_key>/task_label.png
assets/shared/go_button.png
```

如果任務找得到 label 但同一列找不到 `go_button.png`，程式會視為已完成或可領取，直接跳過。

## 資源消耗規則

- `midas`: 免費 + 20 鑽 + 50 鑽。
- `time_travel`: 免費 + 50 鑽，遇到 100 鑽停止。
- `secret_realm`: 只購買迷失森林兩次，然後掃蕩全部。
- `summon`: 只免費召喚。
- `guild_wish`: 只免費祈願。
- `bounty`: 只接白名單；全黑名單或四星以下才刷新；不確定就停止。
- `arena`: 必須避開高於 7000k 的對手。
