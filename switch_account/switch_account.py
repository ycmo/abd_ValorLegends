import argparse
import sys
import time
from pathlib import Path
import pyperclip
import json

# Add project root to sys.path to import src modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
ACCOUNTS_FILE = Path(__file__).resolve().parent / "accounts.json"
DEBUG_DIR = Path(__file__).resolve().parent / "debug_logs"
DEBUG_DIR.mkdir(exist_ok=True)

def load_accounts():
    if not ACCOUNTS_FILE.exists():
        print(f"❌ 找不到帳號設定檔: {ACCOUNTS_FILE}")
        print("請複製 accounts_template.json 並改名為 accounts.json，填入真實的帳密。")
        sys.exit(1)
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

ACCOUNTS = load_accounts()

# Extracted coordinates from screenshots
COORDS = {
    "avatar": (41, 36),
    "account_btn": (178, 375),
    "switch_account_btn": (478, 434),
    "yes_btn": (588, 403),
    "google_login_option": (480, 172),
    "email_login_option": (479, 327),
    "google_acc_select": (341, 222),
    "google_allow_btn": (617, 450),
    "email_acc_field": (477, 225),
    "email_pwd_field": (476, 294),
    "email_login_btn": (365, 399),
    "enter_game": (464, 465)
}

def wait_and_tap(controller: DeviceController, matcher: VisionMatcher, template_name: str, fallback_coord: tuple = None, timeout: int = 15, threshold: float = 0.5, skip_debug: bool = False, force_fallback: bool = False) -> bool:
    # 先等待 1.5 秒讓轉場動畫跑完，避免在動畫中途提早匹配到卻點擊無效
    time.sleep(1.5)
    start = time.time()
    template_path = TEMPLATES_DIR / template_name
    print(f"尋找: {template_name} ...")
    
    # 讀取一次 template，用來決定 ROI 與 Debug
    import cv2
    import numpy as np
    temp_img = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    th, tw = temp_img.shape[:2]
    
    # 恢復 ROI 但大幅放寬範圍，避免慢速電腦全螢幕搜尋過度耗能
    # 同時確保極寬的按鈕 (如登入) 不會被切斷
    roi = None
    if fallback_coord:
        cx, cy = fallback_coord
        # 縮小搜尋範圍為 100x100，避免低門檻 (0.35) 去匹配到遠處的背景雜訊
        rx = max(0, cx - 50 - tw//2)
        ry = max(0, cy - 50 - th//2)
        rw = tw + 100
        rh = th + 100
        roi = (rx, ry, rw, rh)
    
    click_attempts = 0
    last_confidence = 0.0
    last_center = (0, 0)
    
    while time.time() - start < timeout:
        screen = controller.screenshot()
        
        # 每次迴圈開始前，印出當前的最高信心度
        try:
            search_area = screen
            if roi:
                rx, ry, rw, rh = roi
                search_area = screen[ry:ry+rh, rx:rx+rw]
            match_res = cv2.matchTemplate(search_area, temp_img, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(match_res)
            print(f"  [Debug] 目前最高信心度: {max_val:.4f} (目標 >= {threshold})")
        except Exception:
            pass

        res = matcher.match_template(screen, template_path, threshold=threshold, roi=roi)
        
        # 如果之前有點擊過，檢查按鈕是否「消失」、「變暗」或「位置大偏移」
        if click_attempts > 0:
            is_gone = False
            if not res:
                is_gone = True
            elif res.confidence < last_confidence - 0.2:
                is_gone = True
            else:
                dist = ((res.center[0] - last_center[0])**2 + (res.center[1] - last_center[1])**2)**0.5
                if dist > 50:
                    is_gone = True
                    
            if is_gone:
                print("✅ 按鈕已消失或狀態改變(變暗/點擊後畫面更新)，畫面成功跳轉！")
                return True
                
        if not res:
            # 如果沒點過，代表目標還沒出現，繼續等
            time.sleep(2)
            continue

        # 如果走到這裡，代表「目標依然在畫面上，且與上次點擊狀態差不多」
        # 檢查是否已經重複點擊太多次
        if click_attempts >= 3:
            if force_fallback:
                print("⚠️ 點擊 3 次後按鈕依然存在，啟動強制通過 (force_fallback=True)！")
                return True
            
            print("⚠️ 點擊 3 次後按鈕依然存在，強制中斷！")
            if not skip_debug:
                try:
                    import cv2
                    import subprocess
                    debug_screen = screen.copy()
                    
                    cx, cy = res.center
                    cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
                    cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
                    cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
                    
                    if roi:
                        rx, ry, rw, rh = roi
                        cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)
                        
                    debug_path = DEBUG_DIR / f"stuck_debug_{template_name}"
                    ok, buf = cv2.imencode(".png", debug_screen)
                    if ok:
                        debug_path.write_bytes(buf.tobytes())
                        print(f"📸 儲存未跳轉除錯截圖並開啟小畫家: {debug_path.name}")
                        subprocess.Popen(["mspaint", str(debug_path.resolve())])
                        raise RuntimeError(f"異常卡死：已點擊 3 次仍未跳轉，開啟小畫家除錯 ({debug_path.name})")
                except Exception as e:
                    if isinstance(e, RuntimeError): raise e
                    print(f"除錯截圖處理失敗: {e}")
            raise RuntimeError(f"異常卡死：已點擊 3 次仍未跳轉")

        # 進行點擊
        click_attempts += 1
        last_confidence = res.confidence
        last_center = res.center
        print(f"✅ 找到 {template_name} (信心度: {res.confidence:.2f})，點擊 ({res.center[0]}, {res.center[1]}) - 第 {click_attempts} 次嘗試")
        controller.tap(*res.center)
        time.sleep(1.5) # 點完等 1.5 秒讓畫面有時間跳轉
            
    print(f"⚠️ 找不到 {template_name} (已超時 {timeout} 秒)")
    
    if force_fallback and fallback_coord:
        print(f"👉 啟動強制通過，盲點備用座標 {fallback_coord}")
        controller.tap(*fallback_coord)
        time.sleep(2)
        return True
    
    if not skip_debug:
        # 發生錯誤時截圖並標記最後尋找的位置，然後開啟小畫家
        try:
            import cv2
            import subprocess
            debug_screen = controller.screenshot()
            
            if fallback_coord:
                cx, cy = fallback_coord
                # 畫紅色圓圈和十字標記
                cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
                cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
                cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
                
                if roi:
                    rx, ry, rw, rh = roi
                    # 畫綠色矩形來顯示尋找範圍 (ROI)
                    cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)
                    
                debug_path = DEBUG_DIR / f"error_debug_{template_name}"
                ok, buf = cv2.imencode(".png", debug_screen)
                if ok:
                    debug_path.write_bytes(buf.tobytes())
                    print(f"📸 已儲存除錯截圖並開啟小畫家: {debug_path.name}")
                    subprocess.Popen(["mspaint", str(debug_path.resolve())])
                    raise RuntimeError(f"超時未找到目標，已開啟小畫家除錯 ({debug_path.name})")
        except Exception as e:
            if isinstance(e, RuntimeError): raise e
            print(f"除錯截圖處理失敗: {e}")

    raise RuntimeError(f"超時未找到目標，中斷執行")
    return False

def wait_for_appearance(controller: DeviceController, matcher: VisionMatcher, template_name: str, fallback_coord: tuple = None, timeout: int = 10, threshold: float = 0.5) -> bool:
    print(f"尋找: {template_name} ...")
    time.sleep(1.5)
    start = time.time()
    template_path = TEMPLATES_DIR / template_name
    import cv2
    import numpy as np
    temp_img = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    th, tw = temp_img.shape[:2]
    
    roi = None
    if fallback_coord:
        cx, cy = fallback_coord
        rx = max(0, cx - 250 - tw//2)
        ry = max(0, cy - 150 - th//2)
        rw = tw + 500
        rh = th + 300
        roi = (rx, ry, rw, rh)
    
    while time.time() - start < timeout:
        screen = controller.screenshot()
        res = matcher.match_template(screen, template_path, threshold=threshold, roi=roi)
        
        try:
            search_area = screen
            if roi:
                rx, ry, rw, rh = roi
                search_area = screen[ry:ry+rh, rx:rx+rw]
            match_res = cv2.matchTemplate(search_area, temp_img, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(match_res)
            print(f"  [Debug] 目前最高信心度: {max_val:.4f} (目標 >= {threshold})")
        except Exception:
            pass
            
        if res:
            return True
            
        time.sleep(2)
    return False

def paste_text(controller: DeviceController, text: str):
    pyperclip.copy(text)
    time.sleep(0.5) # 確保剪貼簿同步
    # 使用 Android 11+ 的 PASTE Keyevent (279)
    controller.shell(["input", "keyevent", "279"])
    time.sleep(0.5)

def select_server(controller: DeviceController, matcher: VisionMatcher, server_name: str):
    print(f"👉 準備切換到伺服器 {server_name} ...")
    
    # 點擊更換伺服器按鈕 (會彈出列表)
    # 測試階段：將門檻提高回 0.5 觀察是否能正確找到，如果找不到就會跳出小畫家供我們除錯
    wait_and_tap(controller, matcher, "007_帳號切換_0.png", fallback_coord=(494, 373), timeout=30, threshold=0.5)
    time.sleep(2) # 等待列表彈出動畫
    
    screen = controller.screenshot()
    
    # 尋找所有該伺服器的模板圖片
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
        raise RuntimeError(f"大框框內找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")

def switch_account(account_name: str) -> bool:
    if account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(ACCOUNTS.keys())}")
        return False

    account_info = ACCOUNTS[account_name]
    
    # 自動偵測已連線的 ADB 設備
    devices = DeviceController.list_devices()
    if not devices:
        print("錯誤：找不到任何已連線的模擬器，請先執行 reset_adb.bat 或開啟模擬器！")
        return False
        
    # 預設使用第一個找到的設備
    serial = devices[0]
    controller = DeviceController(serial=serial)
    
    if not controller.connect():
        print(f"錯誤：無法連接到模擬器 ({serial})")
        return False

    matcher = VisionMatcher()

    print("📸 開始切換帳號流程...")

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
        print("步驟 4/4: 進入主畫面載入流程...")
        
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
            
        # 2. 檢查是否在進入遊戲的畫面 (006)
        t_006 = TEMPLATES_DIR / "006_點擊進入遊戲_0.png"
        # 限制只在畫面中下方尋找 (x:260~660, y:400~500)，避免誤判其他地方
        res_006 = matcher.match_template(screen, t_006, threshold=0.35, roi=(260, 400, 400, 100))
        if res_006:
            cx, cy = res_006.center
            print(f"👉 找到「進入遊戲」按鈕，點擊座標 ({cx}, {cy}) 並等待 10 秒...")
            controller.tap(cx, cy)
            time.sleep(10)
            continue
            
        # 3. 兩者都沒找到 (轉場動畫、黑屏、載入中)，純等待
        print(f"👉 載入中 (未找到按鈕與寶箱)，等待 10 秒... (第 {loop_idx+1}/10 輪)")
        time.sleep(10)

    if not enter_game_success:
        print("⚠️ 等待掛機畫面超時，可能遇到異常彈出視窗或網路卡死，準備截圖並中斷執行！")
        try:
            import cv2
            import subprocess
            debug_screen = controller.screenshot()
            debug_path = TEMPLATES_DIR.parent / "error_debug_timeout_10loops.png"
            ok, buf = cv2.imencode(".png", debug_screen)
            if ok:
                debug_path.write_bytes(buf.tobytes())
                print(f"📸 已儲存超時除錯截圖並開啟小畫家: {debug_path.name}")
                subprocess.Popen(["mspaint", str(debug_path.resolve())])
        except Exception as e:
            print(f"除錯截圖處理失敗: {e}")
            
        raise RuntimeError("異常卡死：10輪等待掛機畫面超時，已中斷流程！")

    print("✅ 帳號切換流程結束！")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="切換遊戲帳號的小工具")
    parser.add_argument("account", choices=ACCOUNTS.keys(), help="要切換的帳號 (google, 14, tiger)")
    args = parser.parse_args()

    switch_account(args.account)
