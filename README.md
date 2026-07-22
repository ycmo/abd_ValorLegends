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
- 程式執行時的 log、profile 與診斷截圖放 `log/`；`debug/` 保留給對話中的臨時分析資料。
- Codex 擷取作為素材來源的原始圖放 `assets/raw_captures/`。
- 舊架構已封存到 `legacy/20260604_pre_rewrite/`。
- 第一版不自動點每日任務「領取」。

## GUI Launcher

常用指令可以直接開 GUI：

```powershell
.\launcher_gui.bat
```

或手動執行：

```powershell
.\.venv-codex\Scripts\python.exe .\tools\launcher_gui.py
```

GUI 會用 `.venv-codex` 的 Python 執行 Ads2、截圖、切帳號、router、AFK Daily、AFK Midas，並在視窗內顯示輸出。

## 安裝

```powershell
pip install -r requirements.txt
```

## 新電腦與 BlueStacks 轉移

建議新電腦不要直接搬整個 BlueStacks instance。比較穩的方式是重新安裝 BlueStacks，然後用 GitHub 轉移本專案程式與資產。

BlueStacks 建議設定：

- 安裝 BlueStacks 5。
- 建立 Pie 64-bit instance。
- 解析度設定為 `960x540`。
- 開啟 BlueStacks ADB。
- 遊戲內語言、畫質、動畫速度盡量和舊電腦一致。
- 安裝 Valor Legends 並登入帳號。

專案轉移：

```powershell
git clone https://github.com/ycmo/abd_ValorLegends.git
cd abd_ValorLegends
python -m venv .venv-codex
.\.venv-codex\Scripts\Activate.ps1
pip install -r requirements.txt
```

新機驗收指令：

```powershell
python -m src.main devices
python -m src.main check-device
python -m src.main screenshot
python -m src.main detect-scene
```

確認能截圖、辨識主畫面後，再跑每日任務：

```powershell
python -m src.main --debug --debug-actions run-all
```

注意：

- ADB serial 可能從 `emulator-5554` 變成 `127.0.0.1:5555`，可用 `--serial` 或 `VL_ADB_SERIAL` 覆蓋。
- `AwayFromKeyboard/state/` 是本機 runtime 狀態，不納入 Git。
- `switch_account/accounts.json` 已納入 GitHub，換機後 clone 專案即可取得切帳號設定。
- `log/`、`captures/`、`review/`、debug 截圖與錄影不納入 Git。

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
  shared/got/             共用獲得道具 / got overlay template pool
  tasks/<task_key>/       任務專用 template
  raw_captures/           Codex 擷取的原始素材

log/                      執行中的文字 log、profile 與診斷截圖，不納入 git
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
