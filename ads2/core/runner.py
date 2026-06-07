import time
import keyboard
import subprocess
import os
import sys
import shutil
import cv2
import numpy as np
from pathlib import Path

# Setup project root import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src.vision_matcher as vm
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher

# --- 極速快取優化 (不改動外部 src 的情況下動態攔截並快取圖檔) ---
_original_read_image = vm.read_image
_image_cache = {}

def cached_read_image(path, flags=cv2.IMREAD_UNCHANGED):
    # 使用修改時間作為 key，這樣自癒系統存檔後能立刻讀到新圖
    try:
        mtime = path.stat().st_mtime
    except:
        mtime = 0
    cache_key = (str(path), flags, mtime)
    if cache_key not in _image_cache:
        _image_cache[cache_key] = _original_read_image(path, flags)
    return _image_cache[cache_key]

vm.read_image = cached_read_image
# ----------------------------------------------------------------

def crop_red_box_single_image(img_path: Path):
    """專屬於自癒系統的單檔裁切工具 - 輪廓定位 + 極限去紅邊版"""
    data = np.fromfile(str(img_path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None: return None
    
    # 使用 HSV 來精準捕捉小畫家的紅色
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([170, 150, 150]), np.array([180, 255, 255]))
    mask = mask1 | mask2
    
    # 找出所有輪廓（只找外輪廓）
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours: return None
    
    # 找出面積最大的合理輪廓（過濾掉遊戲本身微小的紅點）
    best_roi = None
    max_area = 0
    h, w = img.shape[:2]
    
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        if area < 200 or area > (w * h * 0.9): continue
        if area > max_area:
            max_area = area
            best_roi = (x, y, bw, bh)
            
    if not best_roi: return None
    
    x, y, bw, bh = best_roi
    
    # 裁切出外框區域
    roi_img = img[y:y+bh, x:x+bw]
    roi_mask = mask[y:y+bh, x:x+bw]
    
    y_min, y_max = 0, bh - 1
    x_min, x_max = 0, bw - 1
    
    # 向內縮，直到該行/列的紅色比例極低（代表邊框被切完了）
    while y_min < y_max:
        if np.sum(roi_mask[y_min, x_min:x_max+1] > 0) > (x_max - x_min) * 0.2: y_min += 1
        else: break
            
    while y_max > y_min:
        if np.sum(roi_mask[y_max, x_min:x_max+1] > 0) > (x_max - x_min) * 0.2: y_max -= 1
        else: break
            
    while x_min < x_max:
        if np.sum(roi_mask[y_min:y_max+1, x_min] > 0) > (y_max - y_min) * 0.2: x_min += 1
        else: break
            
    while x_max > x_min:
        if np.sum(roi_mask[y_min:y_max+1, x_max] > 0) > (y_max - y_min) * 0.2: x_max -= 1
        else: break
        
    # 安全保護，往內多縮 1 pixel 確保乾淨
    y_min = min(y_min + 1, y_max)
    y_max = max(y_max - 1, y_min)
    x_min = min(x_min + 1, x_max)
    x_max = max(x_max - 1, x_min)
    
    if x_max <= x_min or y_max <= y_min:
        return None
        
    return roi_img[y_min:y_max+1, x_min:x_max+1]

class ReactiveRunner:
    def __init__(self, serial=None, ad_wait=15, debug=False):
        self.device = DeviceController(serial=serial)
        self.matcher = VisionMatcher()
        self.ad_wait = ad_wait
        self.debug_mode = debug
        
        # 路徑設定
        self.base_dir = Path(__file__).parent.parent
        self.assets_dir = self.base_dir / "assets"
        self.templates_dir = self.assets_dir / "1_templates"
        self.close_icons_dir = self.templates_dir / "close_icons"
        self.got_icons_dir = self.templates_dir / "got_icons"
        self.free_ad_icons_dir = self.templates_dir / "free_ad_icons"
        self.scene_anchors_dir = self.templates_dir / "scene_anchors"
        self.manual_dir = self.assets_dir / "2_manual_captures"
        self.debug_errors_dir = self.assets_dir / "debug_errors"
        
        # 確保資料夾存在
        for d in [self.close_icons_dir, self.got_icons_dir, self.free_ad_icons_dir, self.scene_anchors_dir, self.manual_dir, self.debug_errors_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.free_ad_icons_dir.mkdir(exist_ok=True)
        
        # 相容舊版：如果存在 btn_free_ad.png，自動移動到 free_ad_icons 目錄
        old_btn_path = self.templates_dir / "btn_free_ad.png"
        if old_btn_path.exists():
            shutil.move(str(old_btn_path), str(self.free_ad_icons_dir / "btn_free_ad.png"))
            
        self.click_counts = {}
        
    def setup(self):
        print("[系統] 正在連線 ADB...")
        if not self.device.connect():
            print("❌ [錯誤] ADB 連線失敗！")
            return False
        print("✅ [系統] ADB 連線成功！")
        return True
        
    def check_foreground_app(self):
        try:
            out = self.device.shell(["dumpsys", "window"])
            for line in out.splitlines():
                if "mCurrentFocus" in line:
                    if "/" in line:
                        pkg = line.split(" ")[-1].split("/")[0]
                        pkg = pkg.replace("}", "").strip()
                        return pkg
        except Exception as e:
            print(f"⚠️ [警告] 無法取得前景 APP: {e}")
        return None
        
    def save_debug_error(self, screen, error_name):
        if not self.debug_mode or screen is None:
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{error_name}.png"
        filepath = self.debug_errors_dir / filename
        ok, buf = cv2.imencode('.png', screen)
        if ok:
            filepath.write_bytes(buf.tobytes())
            print(f"📸 [除錯] 已自動儲存異常截圖: {filename}")

    def get_click_point(self, match, count):
        """根據點擊次數，在特徵圖的不同位置進行點擊 (中心 -> 左上 -> 右下 -> 左下 -> 右上)"""
        cx, cy = match.x, match.y
        x, y, w, h = match.bbox
        
        # 為了避免點出邊界，位移量設定為寬高的 1/4 (內縮)
        dx, dy = max(1, w // 4), max(1, h // 4)
        
        if count == 1:
            return cx, cy
        elif count == 2:
            return cx - dx, cy - dy # 左上
        elif count == 3:
            return cx + dx, cy + dy # 右下
        elif count == 4:
            return cx - dx, cy + dy # 左下
        else:
            return cx + dx, cy - dy # 右上

    def handle_esc_interact(self, screen: np.ndarray):
        print("\n==================================================")
        print("🛠️ [自癒系統] 觸發！進入人機協同除錯模式...")
        
        ts = time.strftime("%Y%m%d_%H%M%S")
        comm_dir = self.base_dir / "assets" / "2_communication"
        comm_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存兩份：一份原圖留底討論，一份供小畫家編輯
        orig_path = comm_dir / f"manual_rescue_{ts}_original.png"
        edit_path = comm_dir / f"manual_rescue_{ts}_edit.png"
        
        ok, buf = cv2.imencode('.png', screen)
        if ok:
            orig_path.write_bytes(buf.tobytes())
            edit_path.write_bytes(buf.tobytes())
        
        print(f"📂 [留底] 原圖已保留至: {orig_path.name} (供後續討論使用)")
        print(f"🎨 [自癒系統] 準備開啟小畫家對 {edit_path.name} 進行編輯。")
        print("【操作指引】")
        print("1. 請在小畫家中用「紅色空心矩形」標示你想讓程式點擊的按鈕。")
        print("2. 畫完後按 Ctrl+S 存檔，然後直接關閉小畫家。")
        print("--------------------------------------------------")
        
        subprocess.run(["mspaint", str(edit_path)])
        
        print("⏳ [自癒系統] 偵測到小畫家已關閉，正在自動裁切紅框...")
        
        cropped_img = crop_red_box_single_image(edit_path)
        if cropped_img is not None:
            crop_path = comm_dir / f"crop_{ts}.png"
            ok, buf = cv2.imencode('.png', cropped_img)
            if ok:
                crop_path.write_bytes(buf.tobytes())
                
                print(f"\n✂️ [自癒系統] 裁切成功！產出特徵圖: {crop_path.name}")
                print("【去背指引】")
                print("1. 現在再次打開這張小圖，你可以用「白色」塗掉不需要的遊戲背景。")
                print("2. 為了大幅提升比對效能，目前預設只有「主畫面錨點 (scene_anchors)」支援去背。")
                print("3. 其他按鈕請盡量「緊貼邊緣裁切」，不用塗白去背。")
                print("--------------------------------------------------")
                
                subprocess.run(["mspaint", str(crop_path)])
                
                print("\n🤔 這張圖是什麼類型的特徵？")
                print("1. 關閉按鈕 (放入 close_icons, 預設不去背 / 高速比對)")
                print("2. 獲得道具 (放入 got_icons, 預設不去背 / 高速比對)")
                print("3. 主畫面錨點 (放入 scene_anchors, 支援去背)")
                print("4. 看廣告按鈕 (放入 free_ad_icons, 預設不去背 / 高速比對)")
                
                choice = input("👉 請輸入數字 (1-4): ").strip()
                
                # 是否去背
                do_transparent = False
                if choice == "3":
                    ans = input("❓ 是否需要將白色背景去背(轉透明)? (y/n): ").strip().lower()
                    if ans == "y": do_transparent = True
                
                data = np.fromfile(str(crop_path), dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                
                if do_transparent:
                    if len(img.shape) == 3 and img.shape[2] == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                    white_mask = (img[:,:,0] >= 250) & (img[:,:,1] >= 250) & (img[:,:,2] >= 250)
                    img[white_mask, 3] = 0
                
                # 自動依序編號
                def get_next_name(target_dir, prefix):
                    count = 1
                    while (target_dir / f"{prefix}_{count}.png").exists():
                        count += 1
                    return target_dir / f"{prefix}_{count}.png"
                
                # 根據選擇存檔
                if choice == "1":
                    dest_path = get_next_name(self.close_icons_dir, "close")
                elif choice == "2":
                    dest_path = get_next_name(self.got_icons_dir, "got")
                elif choice == "3":
                    dest_path = get_next_name(self.scene_anchors_dir, "scene")
                elif choice == "4":
                    dest_path = get_next_name(self.free_ad_icons_dir, "free_ad")
                else:
                    dest_path = get_next_name(comm_dir, "unknown")
                    print("未知選項，存放在溝通資料夾。")
                
                ok, buf = cv2.imencode('.png', img)
                if ok:
                    dest_path.write_bytes(buf.tobytes())
                    print(f"✅ [自癒系統] 完美！已將新特徵圖正式加入圖庫: {dest_path}")
        else:
            print("❌ [失敗] 找不到符合的紅框，或裁切失敗。原圖已保留。")
                
        print("▶️ [自癒系統] 人機協同流程結束，恢復大迴圈...")
        print("==================================================\n")
        
    def run(self):
        if not self.setup():
            return
            
        print("\n==================================================")
        print("🚀 啟動無腦反應式大迴圈 (Brainless Reactive Loop)")
        print("==================================================")
        print("-> 每秒持續偵測畫面。")
        print("-> 隨時長按 [ESC] 鍵可呼叫小畫家進行自癒除錯。")
        print("--------------------------------------------------")
        
        # 自訂掃描器：優先比對新圖，並在失敗時印出最高信心值
        def scan_category(paths, threshold, category_name):
            if not paths: return None
            # 依照修改時間排序，最新切好的圖排最前面 (優先比對)
            paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
            
            highest_res = None
            is_first = True
            
            for p in paths:
                res = self.matcher.match_template(screen, p, threshold=0.1)
                
                # 如果是最新的特徵圖 (排序第一個)，且是在最近 10 分鐘內建立的，才印出分數幫助除錯
                # 並且在「驗證廣告消失」的密集輪詢時不印，避免洗版
                if is_first and category_name != "驗證廣告消失":
                    conf = res.confidence if res else 0.0
                    if conf < threshold:
                        try:
                            file_age = time.time() - p.stat().st_mtime
                            if file_age < 600:
                                print(f"👀 [新特徵測試] '{p.parent.name}/{p.name}' 信心度: {conf:.2f} (門檻 {threshold})")
                        except Exception:
                            pass
                is_first = False
                
                if res:
                    if highest_res is None or res.confidence > highest_res.confidence:
                        highest_res = res
                    if res.confidence >= threshold:
                        return res # 只要達到門檻立刻回傳 (因為最新的排前面，所以優先觸發)
                        
            # 除非有達到門檻，否則不再印出「最接近」的無效資訊，保持畫面乾淨
            return None
        
        while True:
            loop_start_time = time.time()
            
            # 1. 攔截 ESC 鍵
            if keyboard.is_pressed('esc'):
                screen = self.device.screenshot()
                if screen is not None:
                    self.handle_esc_interact(screen)
                continue
                
            if self.debug_mode:
                now_str = time.strftime("%H:%M:%S")
                print(f"\r[{now_str}] 📸 正在獲取設備截圖..." + " "*20, end="", flush=True)
                
            cap_start = time.time()
            screen = self.device.screenshot()
            cap_time = time.time() - cap_start
            
            if screen is None:
                time.sleep(1)
                continue
                
            matched_anything = False
            
            match_start = time.time()
            
            # 1. 尋找主畫面錨點 (scene_anchors)
            if self.debug_mode:
                now_str = time.strftime("%H:%M:%S")
                print(f"\r[{now_str}] 🔍 [1/4] 正在比對 主畫面錨點 (scene_anchors)..." + " "*10, end="", flush=True)
                
            scene_paths = list(self.scene_anchors_dir.rglob("*.png"))
            scene_match = scan_category(scene_paths, 0.75, "主畫面")
            
            # 2. 尋找免費廣告 (free_ad_icons)
            if self.debug_mode:
                now_str = time.strftime("%H:%M:%S")
                print(f"\r[{now_str}] 🔍 [2/4] 正在比對 免費廣告 (free_ad_icons)..." + " "*10, end="", flush=True)
                
            free_ad_paths = list(self.free_ad_icons_dir.rglob("*.png"))
            
            keys_to_remove = [k for k in self.click_counts.keys() if k not in [p.name for p in free_ad_paths]]
            for k in keys_to_remove:
                del self.click_counts[k]
                
            free_ad_match = scan_category(free_ad_paths, 0.75, "免費廣告按鈕")
            
            if free_ad_match:
                name = free_ad_match.template_path.name
                self.click_counts[name] = self.click_counts.get(name, 0) + 1
                
                if self.click_counts[name] > 3:
                    print("\n❌ [嚴重錯誤] 免費廣告按鈕連點 3 輪仍無反應，畫面卡死！")
                    self.save_debug_error(screen, f"Stuck_ad_{name}")
                    print("💡 [提示] 你可以長按 ESC 來截圖除錯。程式將自動跳出。")
                    break
                else:
                    print(f"\n📺 [比對成功] 找到免費廣告按鈕: '{name}' (信心值: {free_ad_match.confidence:.2f})")
                    print(f"👉 [目前動作] 執行連點 5 下進入廣告 (第 {self.click_counts[name]}/3 輪)")
                    for i in range(1, 6):
                        tx, ty = self.get_click_point(free_ad_match, i)
                        self.device.tap(tx, ty)
                        time.sleep(0.1)
                        
                        if i % 2 == 0 and i < 5:
                            v_screen = self.device.screenshot()
                            if v_screen is not None:
                                bx, by, bw, bh = free_ad_match.bbox
                                roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                                v_res = self.matcher.match_template(v_screen, free_ad_match.template_path, threshold=0.75, roi=roi)
                                if not v_res or v_res.confidence < free_ad_match.confidence - 0.10:
                                    print(f"✅ [提早確認] 按鈕在第 {i} 下點擊後已消失，中斷連點防誤觸！")
                                    break
                    
                    if self.debug_mode:
                        now_str = time.strftime("%H:%M:%S")
                        print(f"[{now_str}] ⏱️ [Debug 效能] 截圖: {cap_time:.2f}s | 比對: {time.time() - match_start:.2f}s | 總計: {time.time() - loop_start_time:.2f}s")
                    
                    # 不死等，積極輪詢：只要一消失就算成功 (廣告讀取可能需要 5~10 秒)
                    disappeared = False
                    last_verify_conf = 0.0
                    for _ in range(15): # 最多等約 10~15 秒
                        time.sleep(0.5)
                        verify_screen = self.device.screenshot()
                        if verify_screen is None: continue
                        
                        bx, by, bw, bh = free_ad_match.bbox
                        roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                        verify_match = self.matcher.match_template(verify_screen, free_ad_match.template_path, threshold=0.75, roi=roi)
                        
                        if not verify_match or verify_match.confidence < free_ad_match.confidence - 0.10:
                            disappeared = True
                            break
                            
                        last_verify_conf = verify_match.confidence
                    
                    if disappeared:
                        self.click_counts[name] = 0
                        print("✅ [確認] 免費廣告按鈕已消失，成功觸發廣告！")
                        print(f"⏳ [休息] 廣告播放中，進入深度休眠 {self.ad_wait} 秒...")
                        time.sleep(self.ad_wait)
                    else:
                        print(f"⚠️ [警告] 按鈕仍然存在 (最初信心值: {free_ad_match.confidence:.2f} -> 當前信心值: {last_verify_conf:.2f})，點擊可能未生效，準備在下一輪重試...")
                        
                matched_anything = True
                continue
                
            if scene_match:
                print(f"\n🏠 [比對成功] 偵測到主畫面: '{scene_match.template_path.name}' (信心值: {scene_match.confidence:.2f})")
                print("🎉 [任務完成] 無任何免費廣告按鈕，今日所有廣告已觀看完畢！")
                break
                
            # 3. 尋找關閉按鈕 (close_icons)
            if self.debug_mode:
                now_str = time.strftime("%H:%M:%S")
                print(f"\r[{now_str}] 🔍 [3/4] 正在比對 關閉按鈕 (close_icons)..." + " "*10, end="", flush=True)
                
            close_paths = list(self.close_icons_dir.rglob("*.png"))
            close_match = scan_category(close_paths, 0.85, "關閉按鈕")
            
            if close_match:
                name = close_match.template_path.name
                self.click_counts[name] = self.click_counts.get(name, 0) + 1
                
                if self.click_counts[name] > 3:
                    print(f"\n⏭️ [跳過] 關閉按鈕 '{name}' 連點 3 輪仍存在，可能不是按鈕，繼續掃描。")
                    self.save_debug_error(screen, f"Stuck_close_{name}")
                else:
                    print(f"\n🎯 [比對成功] 找到關閉廣告按鈕: '{name}' (信心值: {close_match.confidence:.2f})")
                    print(f"👉 [目前動作] 執行連點 5 下 ({self.click_counts[name]}/3 輪)")
                    for i in range(1, 6):
                        tx, ty = self.get_click_point(close_match, i)
                        self.device.tap(tx, ty)
                        time.sleep(0.1)
                        
                        # 每點兩下檢查一次，避免按鈕消失後誤觸下一頁
                        if i % 2 == 0 and i < 5:
                            v_screen = self.device.screenshot()
                            if v_screen is not None:
                                bx, by, bw, bh = close_match.bbox
                                roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                                v_res = self.matcher.match_template(v_screen, close_match.template_path, threshold=0.85, roi=roi)
                                if not v_res or v_res.confidence < close_match.confidence - 0.10:
                                    print(f"✅ [提早確認] 按鈕在第 {i} 下點擊後已消失，中斷連點防誤觸！")
                                    break
                    
                    if self.debug_mode:
                        now_str = time.strftime("%H:%M:%S")
                        print(f"[{now_str}] ⏱️ [Debug 效能] 截圖: {cap_time:.2f}s | 比對: {time.time() - match_start:.2f}s | 總計: {time.time() - loop_start_time:.2f}s")
                    time.sleep(1)
                    
                matched_anything = True
                continue
                
            # 4. 尋找獲得道具 (got_icons)
            if self.debug_mode:
                now_str = time.strftime("%H:%M:%S")
                print(f"\r[{now_str}] 🔍 [4/4] 正在比對 獲得道具 (got_icons)..." + " "*10, end="", flush=True)
                
            got_paths = list(self.got_icons_dir.rglob("*.png"))
            got_match = scan_category(got_paths, 0.70, "獲得道具")
            
            if got_match:
                name = got_match.template_path.name
                self.click_counts[name] = self.click_counts.get(name, 0) + 1
                
                if self.click_counts[name] > 3:
                    print(f"\n⏭️ [跳過] 獲得道具 '{name}' 連點 3 輪仍存在，可能卡住，繼續掃描。")
                    self.save_debug_error(screen, f"Stuck_got_{name}")
                else:
                    print(f"\n🎁 [比對成功] 找到獲得道具按鈕: '{name}' (信心值: {got_match.confidence:.2f})")
                    print(f"👉 [目前動作] 執行連點 5 下領取 ({self.click_counts[name]}/3 輪)")
                    for i in range(1, 6):
                        tx, ty = self.get_click_point(got_match, i)
                        self.device.tap(tx, ty)
                        time.sleep(0.1)
                        
                        if i % 2 == 0 and i < 5:
                            v_screen = self.device.screenshot()
                            if v_screen is not None:
                                bx, by, bw, bh = got_match.bbox
                                roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                                v_res = self.matcher.match_template(v_screen, got_match.template_path, threshold=0.70, roi=roi)
                                if not v_res or v_res.confidence < got_match.confidence - 0.10:
                                    print(f"✅ [提早確認] 按鈕在第 {i} 下點擊後已消失，中斷連點防誤觸！")
                                    break
                    
                    if self.debug_mode:
                        now_str = time.strftime("%H:%M:%S")
                        print(f"[{now_str}] ⏱️ [Debug 效能] 截圖: {cap_time:.2f}s | 比對: {time.time() - match_start:.2f}s | 總計: {time.time() - loop_start_time:.2f}s")
                    print("⏳ [休息] 領取道具後，等待 0.5 秒...")
                    time.sleep(0.5)
                    
                matched_anything = True
                continue
                
            if not matched_anything:
                # 在沒比對到任何東西時，才去檢查是不是跳出遊戲了
                pkg = self.check_foreground_app()
                if pkg and pkg != "com.ageofeternity.global" and pkg != "Null":
                    print(f"\n⚠️ [警告] 當前 App 為 {pkg}，已跳出遊戲！")
                    self.save_debug_error(screen, f"AppJump_{pkg}")
                    print("👉 [目前動作] 執行 Home 鍵並重新喚醒遊戲...")
                    self.device.shell(["input", "keyevent", "3"])
                    time.sleep(1)
                    self.device.shell(["monkey", "-p", "com.ageofeternity.global", "-c", "android.intent.category.LAUNCHER", "1"])
                    time.sleep(3)
                    continue
                    
                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    total_time = time.time() - loop_start_time
                    match_time = time.time() - match_start
                    print(f"\r[{now_str}] ⏱️ 截圖: {cap_time:.2f}s | 比對: {match_time:.2f}s | 總計: {total_time:.2f}s (觀察中...)" + " "*10, end="", flush=True)
                else:
                    print("👀 [觀察中] 畫面無已知特徵 (正在看廣告或轉場中)... 等待 0.5 秒" + " "*10, end="\r", flush=True)
                
                time.sleep(0.5)
            
        print("\n==================================================")
        print("🛑 廣告模組執行結束")
        print("==================================================")
