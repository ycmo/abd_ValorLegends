import sys
from pathlib import Path

# 1. Update vision_matcher.py
vm_file = Path("E:/antigravity/adb_vl/src/vision_matcher.py")
vm_content = vm_file.read_text(encoding="utf-8")

if "debug_mode: bool = False" not in vm_content:
    vm_target1 = """    def __init__(self, threshold: float = MATCH_THRESHOLD, debug_dir: Optional[Path] = None):
        self.threshold = threshold
        self.debug_dir = debug_dir"""
    vm_replace1 = """    def __init__(self, threshold: float = MATCH_THRESHOLD, debug_dir: Optional[Path] = None, debug_mode: bool = False):
        self.threshold = threshold
        self.debug_dir = debug_dir
        self.debug_mode = debug_mode"""
    vm_content = vm_content.replace(vm_target1, vm_replace1)

    vm_target2 = """        if mask is not None:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED, mask=mask)
            result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        else:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)

        min_score = self.threshold if threshold is None else threshold"""
    vm_replace2 = """        if mask is not None:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED, mask=mask)
            result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        else:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)

        if self.debug_mode:
            _, max_val, _, _ = cv2.minMaxLoc(result)
            print(f"  [Debug-Matcher] 尋找 '{template_path.name}' 最高信心度: {max_val:.4f}")

        min_score = self.threshold if threshold is None else threshold"""
    vm_content = vm_content.replace(vm_target2, vm_replace2)
    vm_file.write_text(vm_content, encoding="utf-8")


# 2. Update switch_account.py
sa_file = Path("E:/antigravity/adb_vl/switch_account/switch_account.py")
sa_content = sa_file.read_text(encoding="utf-8")

# select_server
sa_target1 = """    # 尋找所有該伺服器的模板圖片
    template_paths = list(TEMPLATES_DIR.glob(f"008_伺服器列表_{server_name}*.png"))
    if not template_paths:
        print(f"⚠️ 找不到伺服器圖片 008_伺服器列表_{server_name}*.png，請確認是否截圖！")
        return

    # 使用一個大綠框涵蓋左右兩側歷史紀錄 (x=300~850, y=80~200)
    roi_large = (300, 80, 550, 120)  # x, y, w, h
    
    # 直接使用 match_any，它會在這 550x120 的大綠框內，自動找出所有模板中信心度最高的那一張的「精確座標」
    best_res = matcher.match_any(screen, template_paths, threshold=0.6, roi=roi_large)
    
    if best_res:
        print(f"✅ 成功找到伺服器 {server_name} (信心度: {best_res.confidence:.4f})，點擊座標 ({best_res.center[0]}, {best_res.center[1]})！")
        controller.tap(*best_res.center)
        time.sleep(2)
    else:
        # 截圖除錯
        import cv2
        import subprocess
        debug_path = DEBUG_DIR / f"debug_server_{server_name}.png"
        cv2.rectangle(screen, (300, 80), (850, 200), (0, 255, 0), 2) # 畫出大綠框供除錯
        ok, buf = cv2.imencode(".png", screen)
        if ok:
            debug_path.write_bytes(buf.tobytes())
            print(f"📸 大框框內找不到 {server_name}，已儲存除錯截圖並開啟小畫家: {debug_path.name}")
            subprocess.Popen(["mspaint", str(debug_path.resolve())])
        raise RuntimeError(f"大框框內找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")"""

sa_replace1 = """    # 尋找所有該伺服器的模板圖片
    template_paths = list(TEMPLATES_DIR.glob(f"008_伺服器_{server_name}.png"))
    if not template_paths:
        print(f"⚠️ 找不到伺服器圖片 008_伺服器_{server_name}.png，請確認是否截圖！")
        return

    roi_box = (329, 36, 627, 162)
    best_res = matcher.match_any(screen, template_paths, threshold=0.75, roi=roi_box)
    
    if best_res:
        print(f"✅ 成功找到伺服器 {server_name} (信心度: {best_res.confidence:.4f})，點擊座標 ({best_res.center[0]}, {best_res.center[1]})！")
        controller.tap(*best_res.center)
        
        # 檢查是否有確認切換的彈窗 (加入小迴圈輪詢以應付模擬器卡頓)
        for _ in range(5):
            time.sleep(1)
            screen_after_tap = controller.screenshot()
            confirm_res = matcher.match_template(screen_after_tap, TEMPLATES_DIR / "008_1_確認切換是_0.png", threshold=0.6)
            if confirm_res:
                print("👉 發現確認切換彈窗，點擊『是』...")
                controller.tap(*confirm_res.center)
                time.sleep(2)
                break
    else:
        # 截圖除錯
        import cv2
        import subprocess
        debug_path = DEBUG_DIR / f"debug_server_{server_name}.png"
        x, y, w, h = roi_box
        cv2.rectangle(screen, (x, y), (x + w, y + h), (0, 255, 0), 2)
        ok, buf = cv2.imencode(".png", screen)
        if ok:
            debug_path.write_bytes(buf.tobytes())
            print(f"📸 找不到 {server_name}，已儲存除錯截圖並開啟小畫家: {debug_path.name}")
            subprocess.Popen(["mspaint", str(debug_path.resolve())])
        raise RuntimeError(f"找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")"""

sa_content = sa_content.replace(sa_target1, sa_replace1)


# switch_account signature
sa_target2 = """def switch_account(account_name: str) -> bool:"""
sa_replace2 = """def switch_account(account_name: str, debug_mode: bool = False) -> bool:"""
sa_content = sa_content.replace(sa_target2, sa_replace2)


# early return & setup
sa_target3 = """    if account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(ACCOUNTS.keys())}")
        return False

    account_info = ACCOUNTS[account_name]"""
sa_replace3 = """    if account_name != "toggle" and account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(list(ACCOUNTS.keys()) + ['toggle'])}")
        return False

    if account_name != "toggle":
        account_info = ACCOUNTS[account_name]"""
sa_content = sa_content.replace(sa_target3, sa_replace3)


# VisionMatcher init
sa_target4 = """    matcher = VisionMatcher()"""
sa_replace4 = """    matcher = VisionMatcher(debug_mode=debug_mode)"""
sa_content = sa_content.replace(sa_target4, sa_replace4)


# switch_account core flow
sa_target5 = """    print("📸 開始切換帳號流程...")

    print("步驟 1/4: 點擊頭像與帳號設定")
    # 頭像會隨帳號不同而改變，不使用圖片比對，直接點擊固定座標
    print(f"👉 直接點擊頭像固定座標 {COORDS['avatar']}")
    controller.tap(*COORDS["avatar"])
    time.sleep(1.5)
        
    wait_and_tap(controller, matcher, "001_點擊帳號位置_0.png", fallback_coord=COORDS["account_btn"])
    wait_and_tap(controller, matcher, "002_點擊帳號切換位置_0.png", fallback_coord=COORDS["switch_account_btn"])
    wait_and_tap(controller, matcher, "003_點擊是_0.png", fallback_coord=COORDS["yes_btn"])

    if account_info["type"] == "google":
        print(f"步驟 2/4: 選擇 Google 登入")
        # 只要彈出視窗出現，就直接點擊固定座標
        wait_for_appearance(controller, matcher, "004_Google或信箱_0.png", timeout=10)
        print(f"👉 直接點擊 Google 登入座標 {COORDS['google_login_option']}")
        controller.tap(*COORDS["google_login_option"])
        time.sleep(1.5)

        print("步驟 3/4: 選擇 Google 帳號與授權")
        wait_and_tap(controller, matcher, "005_google登入1_0.png", fallback_coord=COORDS["google_acc_select"])
        
        # 尋找是否有第二階段畫面 (繼續按鈕)，沒找到就下滑再找
        print("👉 開始尋找 Google 授權畫面「繼續」按鈕...")
        found_allow = False
        for swipe_idx in range(4): # 最多滑動 4 次
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

    elif account_info["type"] == "email":
        print(f"步驟 2/4: 選擇信箱登入 ({account_name})")
        # 只要彈出視窗出現，就直接點擊下方的信箱登入座標
        wait_for_appearance(controller, matcher, "004_Google或信箱_0.png", timeout=10)
        print(f"👉 直接點擊信箱登入座標 {COORDS['email_login_option']}")
        controller.tap(*COORDS["email_login_option"])
        time.sleep(1.5)

        print("步驟 3/4: 輸入信箱帳號密碼")
        # 等待輸入畫面出現
        wait_for_appearance(controller, matcher, "005_信箱登入_0.png", fallback_coord=COORDS["email_acc_field"], timeout=5)
        
        # 1. 點擊帳號欄位並貼上帳號
        controller.tap(*COORDS["email_acc_field"])
        time.sleep(1)
        paste_text(controller, account_info["email"])
        
        # 點擊小鍵盤上的「確定」按鈕 (005_信箱登入_3.png)
        # fallback_coord 設為右下角 (910, 500)，這樣 ROI 才會包含到底部白色的輸入列
        wait_and_tap(controller, matcher, "005_信箱登入_3.png", fallback_coord=(910, 500))
        time.sleep(1)
        
        # 2. 點擊密碼欄位並貼上密碼
        controller.tap(*COORDS["email_pwd_field"])
        time.sleep(1)
        paste_text(controller, account_info["password"])

        # 再次點擊小鍵盤上的「確定」按鈕
        wait_and_tap(controller, matcher, "005_信箱登入_3.png", fallback_coord=(910, 500))
        time.sleep(1)

        # 點擊登入按鈕
        wait_and_tap(controller, matcher, "005_信箱登入_2.png", fallback_coord=COORDS["email_login_btn"])

    if account_info["type"] == "google":
        print(f"步驟 4/5: 選擇伺服器 ({account_info.get('server', '預設')}) 並進入遊戲")
        select_server(controller, matcher, account_info.get("server", ""))
    else:
        print("步驟 4/4: 進入主畫面載入流程...")"""

sa_replace5 = """    print("📸 開始起點辨識：檢查當前帳號...")
    current_acc_name = None
    screen = controller.screenshot()
    res_14 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像14.png", threshold=0.7)
    res_311 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像311.png", threshold=0.7)
    res_em3 = matcher.match_template(screen, TEMPLATES_DIR / "000_頭像em3.png", threshold=0.7)
    
    if res_em3:
        current_acc_name = "em3"
        print(f"✅ 辨識成功！當前帳號為：em3 (信心度: {res_em3.confidence:.4f})")
    elif res_311:
        current_acc_name = "311"
        print(f"✅ 辨識成功！當前帳號為：311 (信心度: {res_311.confidence:.4f})")
    elif res_14:
        current_acc_name = "14"
        print(f"✅ 辨識成功！當前帳號為：14 (信心度: {res_14.confidence:.4f})")
    else:
        print("⚠️ 無法辨識當前帳號，預設使用常規流程。")
        
    if account_name == "toggle":
        if current_acc_name == "311":
            account_name = "em3"
        else:
            account_name = "311"
        print(f"🔄 觸發 Toggle 模式：決定目標帳號為 '{account_name}'")
        if account_name not in ACCOUNTS:
            print(f"錯誤：Toggle 目標帳號 '{account_name}' 不存在於設定檔！")
            return False
            
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
        wait_and_tap(controller, matcher, "002_點伺服器_0.png", fallback_coord=(49, 155), timeout=15)

    if not shortcut_triggered:
        if account_info["type"] == "google":
            print(f"步驟 2/4: 選擇 Google 登入")
            wait_for_appearance(controller, matcher, "004_Google或信箱_0.png", timeout=10)
            print(f"👉 直接點擊 Google 登入座標 {COORDS['google_login_option']}")
            controller.tap(*COORDS["google_login_option"])
            time.sleep(1.5)

            print("步驟 3/4: 選擇 Google 帳號與授權")
            wait_and_tap(controller, matcher, "005_google登入1_0.png", fallback_coord=COORDS["google_acc_select"])
            
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

        elif account_info["type"] == "email":
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

    if account_info["type"] == "google":
        print(f"步驟 4/5: 選擇伺服器 ({account_info.get('server', '預設')}) 並進入遊戲")
        select_server(controller, matcher, account_info.get("server", ""))
    else:
        print("步驟 4/4: 進入主畫面載入流程...")"""
sa_content = sa_content.replace(sa_target5, sa_replace5)


# 006 matching
sa_target6 = """        # 2. 檢查是否在進入遊戲的畫面 (006)
        t_006 = TEMPLATES_DIR / "006_點擊進入遊戲_0.png"
        # 限制只在畫面中下方尋找 (x:260~660, y:400~500)，避免誤判其他地方
        res_006 = matcher.match_template(screen, t_006, threshold=0.35, roi=(260, 400, 400, 100))
        if res_006:
            cx, cy = res_006.center
            print(f"👉 找到「進入遊戲」按鈕，點擊座標 ({cx}, {cy}) 並等待 10 秒...")
            controller.tap(cx, cy)
            time.sleep(10)
            continue"""
sa_replace6 = """        # 2. 檢查是否在進入遊戲的畫面 (改為判斷靜態的使用者條款，避免動畫干擾)
        t_006 = TEMPLATES_DIR / "006_登入畫面使用者條款_0.png"
        res_006 = matcher.match_template(screen, t_006, threshold=0.8)
        if res_006:
            print(f"👉 偵測到使用者條款 (確認在登入主畫面)，盲點進入遊戲座標 {COORDS['enter_game']} 並等待 10 秒...")
            controller.tap(*COORDS["enter_game"])
            time.sleep(10)
            continue"""
sa_content = sa_content.replace(sa_target6, sa_replace6)


# argparse
sa_target7 = """    parser.add_argument("account", choices=ACCOUNTS.keys(), help="要切換的帳號 (google, 14, tiger)")
    args = parser.parse_args()

    switch_account(args.account)"""
sa_replace7 = """    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle"], help="要切換的帳號 (google, 14, tiger, toggle)")
    parser.add_argument("--debug", action="store_true", help="開啟 Debug 模式")
    args = parser.parse_args()

    switch_account(args.account, debug_mode=args.debug)"""
sa_content = sa_content.replace(sa_target7, sa_replace7)

sa_file.write_text(sa_content, encoding="utf-8")
print("Done reconstructing all features flawlessly.")
