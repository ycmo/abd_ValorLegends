import sys
from pathlib import Path

target_file = Path("E:/antigravity/adb_vl/switch_account/switch_account.py")
content = target_file.read_text(encoding="utf-8")

helpers = """def detect_current_account(controller: DeviceController, matcher: VisionMatcher) -> str:
    print("📸 開始起點辨識：檢查當前帳號...")
    current_acc_name = None

    for i in range(5):
        screen = controller.screenshot()
        res_14 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像14.png", threshold=0.7)
        res_311 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像311.png", threshold=0.7)
        res_em3 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像em3.png", threshold=0.7)
        res_tiger = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像tiger.png", threshold=0.7)

        if res_em3:
            current_acc_name = "em3"
            print(f"✅ 辨識成功！當前帳號為：em3 (信心度: {res_em3.confidence:.4f})")
            break
        elif res_311:
            current_acc_name = "311"
            print(f"✅ 辨識成功！當前帳號為：311 (信心度: {res_311.confidence:.4f})")
            break
        elif res_14:
            current_acc_name = "14"
            print(f"✅ 辨識成功！當前帳號為：14 (信心度: {res_14.confidence:.4f})")
            break
        elif res_tiger:
            current_acc_name = "tiger"
            print(f"✅ 辨識成功！當前帳號為：tiger (信心度: {res_tiger.confidence:.4f})")
            break

        print(f"⏳ 尚無法辨識當前帳號，等待 1 秒後重試... ({i+1}/5)")
        time.sleep(1)

    if not current_acc_name:
        print("⚠️ 5 次嘗試後仍無法辨識當前帳號，預設使用常規流程。")
    return current_acc_name

def resolve_toggle_target(current_acc_name: str) -> str:
    if current_acc_name == "311":
        return "em3"
    elif current_acc_name == "em3":
        return "311"
    elif current_acc_name == "14":
        return "tiger"
    elif current_acc_name == "tiger":
        return "14"
    else:
        print("錯誤：無法辨識當前帳號，無法執行 Toggle 模式！")
        return None

def login_with_google(controller: DeviceController, matcher: VisionMatcher):
    print("步驟 2/4: 選擇 Google 登入")
    wait_for_appearance(controller, matcher, "004_Google或信箱_0.png", timeout=10)
    print(f"👉 直接點擊 Google 登入座標 {COORDS['google_login_option']}")
    controller.tap(*COORDS["google_login_option"])
    time.sleep(1.5)

    print("步驟 3/4: 選擇 Google 帳號與授權")
    wait_and_tap(controller, matcher, "005_google登入1_0.png", fallback_coord=COORDS["google_acc_select"], timeout=30)
    
    print("👉 開始尋找 Google 授權畫面「繼續」按鈕...")
    found_allow = False
    for swipe_idx in range(4):
        if wait_for_appearance(controller, matcher, "005_google登入2_0.png", fallback_coord=COORDS["google_allow_btn"], timeout=3):
            found_allow = True
            print("✅ 找到繼續按鈕，準備點擊！")
            wait_and_tap(controller, matcher, "005_google登入2_0.png", fallback_coord=COORDS["google_allow_btn"], timeout=10)
            break
            
        print(f"👉 畫面中未看到繼續按鈕，執行第 {swipe_idx+1} 次下滑動作...")
        controller.swipe(480, 450, 480, 100, duration_ms=800)
        time.sleep(1.5)
        
    if not found_allow:
        print("⚠️ 滑動多次仍未找到繼續按鈕，直接盲點備用座標！")
        controller.tap(*COORDS["google_allow_btn"])
        
    print("⏳ 等待 10 秒讓 Google 登入驗證與主畫面載入...")
    time.sleep(10)

def login_with_email(controller: DeviceController, matcher: VisionMatcher, account_info: dict, account_name: str):
    print(f"步驟 2/4: 選擇信箱登入 ({account_name})")
    wait_for_appearance(controller, matcher, "004_Google或信箱_0.png", timeout=10)
    print(f"👉 直接點擊信箱登入座標 {COORDS['email_login_option']}")
    controller.tap(*COORDS["email_login_option"])
    time.sleep(1.5)

    print("步驟 3/4: 輸入信箱帳號密碼")
    wait_for_appearance(controller, matcher, "005_信箱登入_0.png", fallback_coord=COORDS["email_acc_field"], timeout=5)
    
    controller.tap(*COORDS["email_acc_field"])
    time.sleep(1)
    paste_text(controller, account_info["email"])
    
    wait_and_tap(controller, matcher, "005_信箱登入_3.png", fallback_coord=(910, 500))
    time.sleep(1)
    
    controller.tap(*COORDS["email_pwd_field"])
    time.sleep(1)
    paste_text(controller, account_info["password"])

    wait_and_tap(controller, matcher, "005_信箱登入_3.png", fallback_coord=(910, 500))
    time.sleep(1)

    wait_and_tap(controller, matcher, "005_信箱登入_2.png", fallback_coord=COORDS["email_login_btn"])

def wait_for_game_entry(controller: DeviceController, matcher: VisionMatcher) -> bool:
    print("⏳ 開始檢查「進入遊戲」按鈕或「掛機寶箱」...")
    enter_game_success = False
    # 最大嘗試 10 輪 (因為有時候點擊或網路載入會很久)
    for loop_idx in range(10):
        screen = controller.screenshot()
        
        # 1. 優先檢查是否已經進入掛機畫面 (009)
        t_009 = TEMPLATES_DIR / "009_登入掛機成功_0.png"
        res_009 = matcher.match_template(screen, t_009, threshold=0.5)
        if res_009:
            print("🎉 偵測到掛機寶箱畫面，登入成功！")
            enter_game_success = True
            break
            
        # 2. 檢查是否在進入遊戲的畫面 (改為判斷靜態的使用者條款，避免動畫干擾)
        t_006 = TEMPLATES_DIR / "006_登入畫面使用者條款_0.png"
        res_006 = matcher.match_template(screen, t_006, threshold=0.8, debug_mode=True)
        if res_006:
            print(f"👉 偵測到使用者條款 (確認在登入主畫面)，盲點進入遊戲座標 {COORDS['enter_game']} 並等待 10 秒...")
            controller.tap(*COORDS["enter_game"])
            time.sleep(10)
            continue
            
        # 3. 兩者都沒找到 (轉場動畫、黑屏、載入中)，純等待
        print(f"👉 載入中 (未找到按鈕與寶箱)，等待 10 秒... (第 {loop_idx+1}/10 輪)")
        time.sleep(10)

    if not enter_game_success:
        print("⚠️ 等待掛機畫面超時，可能遇到異常彈出視窗或網路卡死，準備截圖並中斷執行！")
        try:
            debug_screen = controller.screenshot()
            debug_path = TEMPLATES_DIR.parent / "error_debug_timeout_10loops.png"
            save_and_show_debug(debug_screen, debug_path)
        except Exception as e:
            print(f"除錯截圖處理失敗: {e}")
            
        raise RuntimeError("異常卡死：10輪等待掛機畫面超時，已中斷流程！")

    print("✅ 帳號切換流程結束！")
    return True

def switch_account"""

content = content.replace("def switch_account", helpers)

start_idx = content.find("    matcher = VisionMatcher(debug_mode=debug_mode)")
end_idx = content.find("if __name__ ==")
original_body = content[start_idx:end_idx]

new_body = """    matcher = VisionMatcher(debug_mode=debug_mode)

    current_acc_name = detect_current_account(controller, matcher)
        
    if account_name == "toggle":
        target = resolve_toggle_target(current_acc_name)
        if not target:
            return False
        account_name = target
        print(f"🔄 觸發 Toggle 模式：決定目標帳號為 '{account_name}'")
        if account_name not in ACCOUNTS:
            print(f"錯誤：Toggle 目標帳號 '{account_name}' 不存在於設定檔！")
            return False
            
    # 這裡才重新載入真正要切換的帳號資訊
    account_info = ACCOUNTS[account_name]
    
    shortcut_triggered = False
    if current_acc_name and current_acc_name in ACCOUNTS and account_name in ACCOUNTS:
        curr_type = ACCOUNTS[current_acc_name]["type"]
        tgt_type = ACCOUNTS[account_name]["type"]
        if curr_type == "google" and tgt_type == "google":
            shortcut_triggered = True
            print("⚡ 觸發超級捷徑：目前為 Google 帳號，目標也是 Google 帳號，跳過完整登出流程！")

    print("步驟 1/4: 點擊頭像與帳號設定")
    print(f"👉 直接點擊頭像固定座標 {COORDS['avatar']}")
    controller.tap(*COORDS["avatar"])
    time.sleep(1.5)

    if not shortcut_triggered:
        wait_and_tap(controller, matcher, "001_點擊帳號位置_0.png", fallback_coord=COORDS["account_btn"])
        wait_and_tap(controller, matcher, "002_點擊帳號切換位置_0.png", fallback_coord=COORDS["switch_account_btn"])
        wait_and_tap(controller, matcher, "003_點擊是_0.png", fallback_coord=COORDS["yes_btn"])
    else:
        print("👉 點擊左側「伺服器」分頁...")
        wait_for_appearance(controller, matcher, "002_點伺服器_0.png", fallback_coord=(49, 155), timeout=5)
        controller.tap(49, 155)
        time.sleep(1.5)

    if not shortcut_triggered:
        if account_info["type"] == "google":
            login_with_google(controller, matcher)
        elif account_info["type"] == "email":
            login_with_email(controller, matcher, account_info, account_name)

    if account_info["type"] == "google":
        print(f"步驟 4/5: 選擇伺服器 ({account_info.get('server', '預設')}) 並進入遊戲")
        select_server(controller, matcher, account_info.get("server", ""), skip_open=shortcut_triggered)
    else:
        print("步驟 4/4: 進入主畫面載入流程...")
        
    return wait_for_game_entry(controller, matcher)


"""

content = content.replace(original_body, new_body)

target_file.write_text(content, encoding="utf-8")
print("Refactoring Phase 2 complete.")
