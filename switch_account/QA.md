# 帳號切換 (switch_account) 模組更新任務

## 🛑 新增需求：處理登入過程中的臨時彈出廣告
使用者回報在進入掛機寶箱前，偶爾會跳出「臨時跳出廣告」。
我們已經成功將廣告中的「關閉按鈕」或「跳過按鈕」擷取為範本圖片 `009_關閉廣告_0.png`。
現在需要將這個防呆機制整合到 `wait_for_game_entry` 函式中，讓腳本能自動偵測並關閉它。

## 🎯 實作指令 (Prompt for RD)
請進入 `E:\antigravity\adb_vl\switch_account\switch_account.py`，修改 `wait_for_game_entry` 函式：

1. **在 `wait_for_game_entry` 迴圈中加入廣告偵測**：
   找到這段迴圈：
   ```python
   for loop_idx in range(MAX_GAME_ENTRY_ATTEMPTS):
       screen = controller.screenshot()

       # 1. 優先檢查是否已經進入掛機畫面 (009)
       t_009 = TEMPLATES_DIR / "009_登入掛機成功_0.png"
       res_009 = matcher.match_template(screen, t_009, threshold=0.5)
       if res_009:
           print("🎉 偵測到掛機寶箱畫面，登入成功！")
           enter_game_success = True
           break
   ```

   請在上述 `1.` 的下方，新增一段 `1.5` 的廣告攔截邏輯：
   ```python
       # 1.5. 檢查是否有臨時彈出廣告
       t_ad = TEMPLATES_DIR / "009_關閉廣告_0.png"
       res_ad = matcher.match_template(screen, t_ad, threshold=0.7)
       if res_ad:
           print(f"👉 偵測到臨時彈出廣告，點擊關閉 ({res_ad.center[0]}, {res_ad.center[1]})...")
           controller.tap(*res_ad.center)
           time.sleep(2)  # 等待廣告關閉動畫
           continue  # 回到迴圈開頭重新截圖確認狀態
   ```

2. **確認邏輯無誤後**：
   儲存檔案，這項更新不影響原有的流程。

## ✅ 驗證標準
執行 `python -m py_compile switch_account\switch_account.py` 確認語法正常。
後續在實機測試時，若出現該廣告，應能在終端機看到 `👉 偵測到臨時彈出廣告，點擊關閉...` 並順利關閉廣告進入寶箱畫面。
