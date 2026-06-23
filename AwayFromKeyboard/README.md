# AwayFromKeyboard

## 點金手自動循環

雙帳號：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --auto
```

全部帳號並保留操作截圖：

```powershell
python.exe AwayFromKeyboard\loop_toggle_midas.py --auto --all --debug-actions
```

## 點金手進場規則

重複執行點金手時，每日任務可能已經完成並變灰，因此 AFK 流程不得從每日任務尋找點金手。

固定流程如下：

1. 使用 `AwayFromKeyboard/route_screenshots/點金手` 從主畫面開啟點金手。
2. 確認目前畫面就是點金手視窗。
3. 執行 `run-current-scene-task midas` 的 current-scene 邏輯。
4. 若 AFK route 沒有成功開啟點金手，直接報錯並保留現場，不得 fallback 到每日任務。

`loop_toggle_midas.py --auto` 會在同一個程序中直接執行 AFK route 與 `MidasTask.execute_auto()`；一般 Router 配置則使用：

```text
-m src.main --debug run-current-scene-task midas
```

請勿把 AFK 點金手配置改回 `run-task midas`。

`loop_toggle_midas.py` 的 auto 與非 auto 模式都直接使用上述 AFK route 和 `MidasTask`，不讀取 `afk_tasks.ini`。`afk_tasks.ini` 的點金手設定只供 `loop_afk.py` 等通用 Router 流程使用。

若點擊金幣 `+` 後沒有出現點金手視窗，程式會用 Router 的 `gift_pack_label.png` 檢查是否被臨時禮包廣告遮擋。確認是已知廣告後會關閉、恢復主城並重新進入點金手，最多恢復 3 次。每次視窗驗證失敗都會無條件保存畫面到 `captures/failures/midas/`；`--debug-actions` 只影響額外的動作前後截圖。

## Auto 輪轉順序

- 第一次啟動及後續每次醒來都從 `em3` 開始，依帳號順序完整輪轉一圈，最後回到 `em3`。
- `--all` 固定使用 `em3 -> 311 -> tiger -> 14 -> em3`，以減少 Google 與 Email 登入流程互切。此順序不依賴也不會修改 `accounts.json` 的排列。
- 任一帳號沒有成功點金時才讀取冷卻；冷卻不超過 5 分鐘時留在該帳號休眠，時間到後重試。
- 輪轉途中若 OCR 無法辨識冷卻，視為超過 5 分鐘並直接切換下一帳號，不中斷整輪。
- 完整一輪後回到 `em3` 再執行一次點金並讀取冷卻；只有這次 OCR 失敗才改為休眠 2 小時。
- 大休眠會從 `em3` 冷卻扣除 4 分鐘，預留醒來後處理登入狀態的時間。
