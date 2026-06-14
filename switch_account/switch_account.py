import argparse
import sys
import time
from pathlib import Path
import pyperclip
import json
import cv2
import numpy as np
import subprocess

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

TOGGLE_MAP = {"311": "em3", "em3": "311", "14": "tiger", "tiger": "14"}

SERVER_BTN_TIMEOUT_SEC = 60
MAX_GAME_ENTRY_ATTEMPTS = 30

# Extracted coordinates from screenshots
COORDS = {
    "avatar": (41, 36),
    "account_btn": (178, 375),
    "server_list_btn": (494, 373),
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

def save_and_show_debug(screen, debug_path: Path, center: tuple = None, roi: tuple = None):
    debug_screen = screen.copy()
    if center:
        cx, cy = center
        cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
        cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
        cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
    if roi:
        rx, ry, rw, rh = roi
        cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)

    ok, buf = cv2.imencode(".png", debug_screen)
    if ok:
        debug_path.write_bytes(buf.tobytes())
        print(f"📸 已儲存除錯截圖並開啟小畫家: {debug_path.name}")
        subprocess.Popen(["mspaint", str(debug_path.resolve())])

def wait_and_tap(controller: DeviceController, matcher: VisionMatcher, template_name: str, fallback_coord: tuple = None, timeout: int = 15, threshold: float = 0.5, skip_debug: bool = False, force_fallback: bool = False) -> bool:
    # 先等待 1.5 秒讓轉場動畫跑完，避免在動畫中途提早匹配到卻點擊無效
    time.sleep(1.5)
    start = time.time()
    template_path = TEMPLATES_DIR / template_name
    print(f"尋找: {template_name} ...")
    
    # 讀取一次 template，用來決定 ROI 與 Debug
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
                    debug_path = DEBUG_DIR / f"stuck_debug_{template_name}"
                    save_and_show_debug(screen, debug_path, center=res.center, roi=roi)
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
            debug_screen = controller.screenshot()
            debug_path = DEBUG_DIR / f"error_debug_{template_name}"
            save_and_show_debug(debug_screen, debug_path, center=fallback_coord, roi=roi)
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

def select_server(controller: DeviceController, matcher: VisionMatcher, server_name: str, skip_open: bool = False):
    print(f"👉 準備切換到伺服器 {server_name} ...")
    
    if not skip_open:
        # 點擊更換伺服器按鈕 (會彈出列表)
        # 測試階段：將門檻提高回 0.5 觀察是否能正確找到，如果找不到就會跳出小畫家供我們除錯
        wait_and_tap(controller, matcher, "007_帳號切換_0.png", fallback_coord=COORDS["server_list_btn"], timeout=SERVER_BTN_TIMEOUT_SEC, threshold=0.5)
        time.sleep(2) # 等待列表彈出動畫
    else:
        print("⚡ 因超級捷徑已展開伺服器列表，跳過點擊「007_帳號切換」步驟")
    
    screen = controller.screenshot()
    
    # 尋找所有該伺服器的模板圖片
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
        debug_path = DEBUG_DIR / f"debug_server_{server_name}.png"
        save_and_show_debug(screen, debug_path, roi=roi_box)
        raise RuntimeError(f"找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")

def detect_current_account(controller: DeviceController, matcher: VisionMatcher) -> str:
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

def resolve_next_target(current_acc_name: str) -> str:
    if not current_acc_name:
        return None
    acc_list = list(ACCOUNTS.keys())
    if current_acc_name not in acc_list:
        return None
    current_idx = acc_list.index(current_acc_name)
    next_idx = (current_idx + 1) % len(acc_list)
    return acc_list[next_idx]

def resolve_toggle_target(current_acc_name: str) -> str:
    return TOGGLE_MAP.get(current_acc_name)

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
    print(f"⏳ 開始檢查「進入遊戲」按鈕或「掛機寶箱」 (最大等待 {MAX_GAME_ENTRY_ATTEMPTS} 輪)...")
    enter_game_success = False
    
    for loop_idx in range(MAX_GAME_ENTRY_ATTEMPTS):
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
            print(f"👉 偵測到使用者條款 (確認在登入主畫面)，盲點進入遊戲座標 {COORDS['enter_game']}...")

            # 加入長時連打迴圈：確認點擊生效，給予充足時間直到條款畫面消失
            max_taps = 6
            for tap_idx in range(max_taps):
                controller.tap(*COORDS["enter_game"])
                # 放長等待時間至 10 秒，應付遊戲真實的載入延遲
                time.sleep(10)

                check_screen = controller.screenshot()
                # 稍微放寬 threshold 至 0.75，避免動畫干擾導致誤判為消失
                if not matcher.match_template(check_screen, t_006, threshold=0.75):
                    print("✅ 畫面已成功跳轉 (使用者條款消失)！")
                    break
                print(f"⚠️ 依舊偵測到使用者條款，再次點擊... ({tap_idx+1}/{max_taps})")

            # 結束微迴圈後，直接 continue 交由外層大迴圈繼續偵測掛機寶箱
            continue
            
        # 3. 兩者都沒找到 (轉場動畫、黑屏、載入中)，純等待
        print(f"👉 載入中 (未找到按鈕與寶箱)，等待 10 秒... (第 {loop_idx+1}/{MAX_GAME_ENTRY_ATTEMPTS} 輪)")
        time.sleep(10)

    if not enter_game_success:
        print("⚠️ 等待掛機畫面超時，可能遇到異常彈出視窗或網路卡死，準備截圖並中斷執行！")
        try:
            debug_screen = controller.screenshot()
            debug_path = TEMPLATES_DIR.parent / "error_debug_timeout_loops.png"
            save_and_show_debug(debug_screen, debug_path)
        except Exception as e:
            print(f"除錯截圖處理失敗: {e}")
            
        raise RuntimeError(f"異常卡死：{MAX_GAME_ENTRY_ATTEMPTS}輪等待掛機畫面超時，已中斷流程！")

    print("✅ 帳號切換流程結束！")
    return True

def switch_account(account_name: str, debug_mode: bool = False) -> bool:
    MACRO_RESOLVERS = {
        "toggle": resolve_toggle_target,
        "next": resolve_next_target,
    }

    if account_name not in MACRO_RESOLVERS and account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(list(ACCOUNTS.keys()) + list(MACRO_RESOLVERS.keys()))}")
        return False
    
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

    matcher = VisionMatcher(debug_mode=debug_mode)

    current_acc_name = detect_current_account(controller, matcher)
        
    if account_name in MACRO_RESOLVERS:
        target = MACRO_RESOLVERS[account_name](current_acc_name)
        if not target:
            print(f"錯誤：無法解析 {account_name} 模式下的目標帳號！(可能無法辨識當前畫面)")
            return False
        print(f"🔄 觸發 {account_name} 模式：動態推導目標帳號為 '{target}'")
        account_name = target
            
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="切換遊戲帳號的小工具")
    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle", "next"], help="要切換的帳號 (對應設定檔名稱, toggle, 或 next)")
    parser.add_argument("--debug", action="store_true", help="開啟 Debug 模式")
    args = parser.parse_args()

    switch_account(args.account, debug_mode=args.debug)
