# 帳號切換 (switch_account) 模組重構計畫 (Refactoring Plan)

## 🎯 Phase 2: 拆解神級主程序 (中風險)
**目標**：將 `switch_account()` 這個超過 200 行的「上帝函式 (God Function)」拆解成多個專責的輔助子函式，讓主流程變得像閱讀目錄一樣清晰。

**實作指令 (Prompt for RD)**：
請進入 `E:\antigravity\adb_vl\switch_account\switch_account.py`，在 `select_server` 函式下方、`switch_account` 上方，新增以下 5 個輔助函式，並將 `switch_account` 中對應的程式碼抽離出來：

1. **`detect_current_account(controller: DeviceController, matcher: VisionMatcher) -> str`**：
   - 負責執行那 5 次截圖輪詢找頭像的邏輯。
   - 找到時回傳 `14`, `311`, `em3`, 或 `tiger`；若失敗則回傳 `None`。

2. **`resolve_toggle_target(current_acc_name: str) -> str`**：
   - 負責處理 `311 <-> em3` 以及 `14 <-> tiger` 的對接邏輯。
   - 若無法辨識則印出錯誤並回傳 `None`。

3. **`login_with_google(controller: DeviceController, matcher: VisionMatcher)`**：
   - 負責封裝從點選「Google 登入」按鈕、選帳號、向下滑動找「繼續」並盲點，最後等候 10 秒的所有流程。

4. **`login_with_email(controller: DeviceController, matcher: VisionMatcher, account_info: dict, account_name: str)`**：
   - 負責封裝信箱密碼輸入、`paste_text` 以及最終點擊登入的所有流程。

5. **`wait_for_game_entry(controller: DeviceController, matcher: VisionMatcher) -> bool`**：
   - 負責那 10 次尋找「使用者條款」或「掛機寶箱」的輪詢迴圈。
   - 若成功進入回傳 `True`，若 10 次超時則觸發除錯截圖並拋出 `RuntimeError`。

**改寫後的主函式 `switch_account` 預期輪廓**：
重構後的 `switch_account` 應該極度簡潔，骨架如下：
```python
def switch_account(account_name: str, debug_mode: bool = False) -> bool:
    # 1. 連線設備與初始化 Matcher (維持不變)
    
    # 2. 偵測當前帳號
    current_acc_name = detect_current_account(controller, matcher)
    
    # 3. 處理 Toggle
    if account_name == "toggle":
        account_name = resolve_toggle_target(current_acc_name)
        if not account_name: return False
        if account_name not in ACCOUNTS: return False
        
    account_info = ACCOUNTS[account_name]
    
    # 4. 判斷是否走超級捷徑
    shortcut_triggered = (current_acc_name in ACCOUNTS and 
                          ACCOUNTS[current_acc_name]["type"] == "google" and 
                          account_info["type"] == "google")
    
    # 5. 執行前半段流程 (登出 or 捷徑點伺服器)
    # ...
    
    # 6. 執行後半段流程 (登入)
    if not shortcut_triggered:
        if account_info["type"] == "google":
            login_with_google(controller, matcher)
        elif account_info["type"] == "email":
            login_with_email(controller, matcher, account_info, account_name)
            
    # 7. 選擇伺服器
    if account_info["type"] == "google":
        select_server(controller, matcher, account_info.get("server", ""), skip_open=shortcut_triggered)
        
    # 8. 等待進入遊戲
    return wait_for_game_entry(controller, matcher)
```

## ✅ 驗證標準
完成拆分後，確保不遺漏任何變數（例如 `COORDS` 的存取）。
請執行 `python -m py_compile switch_account\switch_account.py` 確認無語法錯誤，接著執行 Unit Test 確認重構沒有破壞邏輯。