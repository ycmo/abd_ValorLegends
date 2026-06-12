import cv2
import numpy as np
import time
from pathlib import Path
import sys

# 將專案根目錄加入 sys.path 以便匯入 src 模組
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 若獨立測試時尚未有 DeviceController，使用延遲載入或在測試中 Mock
try:
    from src.adb_controller import DeviceController
except ImportError:
    DeviceController = None

class RedBoxFinder:
    def find_largest_red_box_info(self, img_path: Path) -> tuple[tuple[int, int], tuple[int, int, int, int], np.ndarray]:
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"無法讀取圖片: {img_path}")
            
        # 嚴格抓取紅色 (雙遮罩邏輯)
        lower_red = np.array([30, 20, 230])
        upper_red = np.array([50, 40, 255])
        mask1 = cv2.inRange(img, lower_red, upper_red)
        
        # 容許純紅
        lower_red2 = np.array([0, 0, 240])
        upper_red2 = np.array([10, 10, 255])
        mask2 = cv2.inRange(img, lower_red2, upper_red2)
        
        mask = mask1 | mask2
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_area = 0
        best_center = None
        best_rect = None
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w < 15 or h < 15:
                continue
            
            area = w * h
            if area > best_area:
                # ====== 智慧去紅邊 ======
                sub_mask = mask[y:y+h, x:x+w]
                mid_x1, mid_x2 = int(w * 0.3), int(w * 0.7)
                mid_y1, mid_y2 = int(h * 0.3), int(h * 0.7)
                
                row_sums_mid = np.sum(sub_mask[:, mid_x1:mid_x2] > 0, axis=1)
                mid_w = mid_x2 - mid_x1
                
                top = 0
                while top < h and row_sums_mid[top] > mid_w * 0.3:
                    top += 1
                    
                bottom = h - 1
                while bottom >= 0 and row_sums_mid[bottom] > mid_w * 0.3:
                    bottom -= 1
                    
                col_sums_mid = np.sum(sub_mask[mid_y1:mid_y2, :] > 0, axis=0)
                mid_h = mid_y2 - mid_y1
                
                left = 0
                while left < w and col_sums_mid[left] > mid_h * 0.3:
                    left += 1
                    
                right = w - 1
                while right >= 0 and col_sums_mid[right] > mid_h * 0.3:
                    right -= 1
                
                if top > bottom or left > right:
                    inner_x, inner_y, inner_w, inner_h = x, y, w, h
                else:
                    inner_x = x + left
                    inner_y = y + top
                    inner_w = right - left + 1
                    inner_h = bottom - top + 1
                # =======================

                best_area = area
                best_center = (x + w // 2, y + h // 2)
                best_rect = (inner_x, inner_y, inner_w, inner_h)
                
        if not best_center:
            raise ValueError(f"在 {img_path.name} 中找不到符合條件的紅框！")
            
        return best_center, best_rect, img

class RouteNavigator:
    def __init__(self, route_name: str, controller=None, finder=None, base_dir=None):
        self.route_name = route_name
        
        if controller is not None:
            self.controller = controller
        else:
            if DeviceController is None:
                raise ImportError("找不到 DeviceController 模組且未提供 Mock Controller。")
            self.controller = DeviceController()
            
        self.finder = finder if finder is not None else RedBoxFinder()
        
        if base_dir is None:
            # 預設 base_dir 為 AwayFromKeyboard/
            self.base_dir = Path(__file__).resolve().parent.parent
        else:
            self.base_dir = Path(base_dir)
            
        self.route_dir = self.base_dir / "route_screenshots" / self.route_name

    def execute_route(self, phase="enter"):
        if not self.route_dir.exists() or not self.route_dir.is_dir():
            raise FileNotFoundError(f"路由目錄不存在: {self.route_dir}")
            
        png_files = sorted(self.route_dir.glob("*.png"))
        if not png_files:
            raise FileNotFoundError(f"在 {self.route_dir} 中找不到任何 .png 檔案")
            
        if phase == "enter":
            target_files = [f for f in png_files if f.name[0].isdigit()]
        elif phase == "exit":
            target_files = [f for f in png_files if f.name.lower().startswith('r')]
        else:
            target_files = png_files
            
        if not target_files:
            return
            
        for img_path in target_files:
            threshold = 0.5 if "_lowconf" in img_path.name else 0.7
            (cx, cy), (x, y, w, h), original_img = self.finder.find_largest_red_box_info(img_path)
            
            # 從原圖中切下目標當作 template
            template = original_img[y:y+h, x:x+w]
            
            # 取得當前實機畫面 (相容 get_screen 或是 screenshot)
            get_screen_func = getattr(self.controller, "get_screen", getattr(self.controller, "screenshot", None))
            screen = get_screen_func() if get_screen_func else None
            
            if get_screen_func is None:
                print(f"[Fallback] 無法取得實機畫面 -> 退回點擊原始紅框中心 ({cx}, {cy})")
                self.controller.tap(cx, cy)
                time.sleep(2.0)
                continue

            success = False
            max_val = 0.0
            
            is_swipe_v = "_swipe_v" in img_path.name
            is_swipe_h = "_swipe_h" in img_path.name
            
            if is_swipe_v or is_swipe_h:
                # 第一階段：先比對一次
                screen = get_screen_func()
                if screen is not None:
                    sh, sw = screen.shape[:2]
                    if is_swipe_v:
                        roi_x1 = max(0, x - 50)
                        roi_x2 = min(sw, x + w + 50)
                        roi_y1 = 0
                        roi_y2 = sh
                    else: # is_swipe_h
                        roi_x1 = 0
                        roi_x2 = sw
                        roi_y1 = max(0, y - 150)
                        roi_y2 = min(sh, y + h + 150)
                        
                    screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                    res = cv2.matchTemplate(screen_roi, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val >= threshold:
                        abs_cx = roi_x1 + max_loc[0] + w // 2
                        abs_cy = roi_y1 + max_loc[1] + h // 2
                        print(f"[Router] 執行 {img_path.name} -> 找到浮動目標 (信心度 {max_val:.2f}) -> 點擊座標 ({abs_cx}, {abs_cy})")
                        self.controller.tap(abs_cx, abs_cy)
                        time.sleep(2.0)
                        success = True

                # 第二階段：滑動後再比對一次
                if not success and screen is not None:
                    print(f"  [Debug] 尋找 {img_path.name} 失敗 (信心度 {max_val:.2f})，準備動態滑動...")
                    
                    # 動態滑動
                    cx_orig = x + w // 2
                    cy_orig = y + h // 2
                    
                    if is_swipe_v:
                        start_y = min(sh - 10, cy_orig + 150)
                        end_y = max(10, cy_orig - 150)
                        self.controller.swipe(cx_orig, start_y, cx_orig, end_y, duration_ms=500)
                    else:
                        start_x = min(sw - 10, cx_orig + 150)
                        end_x = max(10, cx_orig - 150)
                        self.controller.swipe(start_x, cy_orig, end_x, cy_orig, duration_ms=500)
                        
                    time.sleep(1.5)
                    
                    screen = get_screen_func()
                    if screen is not None:
                        sh, sw = screen.shape[:2]
                        if is_swipe_v:
                            roi_x1 = max(0, x - 50)
                            roi_x2 = min(sw, x + w + 50)
                            roi_y1 = 0
                            roi_y2 = sh
                        else:
                            roi_x1 = 0
                            roi_x2 = sw
                            roi_y1 = max(0, y - 150)
                            roi_y2 = min(sh, y + h + 150)
                            
                        screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                        res = cv2.matchTemplate(screen_roi, template, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        
                        if max_val >= threshold:
                            abs_cx = roi_x1 + max_loc[0] + w // 2
                            abs_cy = roi_y1 + max_loc[1] + h // 2
                            print(f"[Router] 滑動後執行 {img_path.name} -> 找到浮動目標 (信心度 {max_val:.2f}) -> 點擊座標 ({abs_cx}, {abs_cy})")
                            self.controller.tap(abs_cx, abs_cy)
                            time.sleep(2.0)
                            success = True
            else:
                for attempt in range(20):
                    screen = get_screen_func()
                    if screen is None:
                        continue
                    
                    # 取得畫面的長寬
                    sh, sw = screen.shape[:2]
                    
                    # 放寬 ROI: x 軸放寬 50，y 軸放寬 150
                    roi_x1 = max(0, x - 50)
                    roi_x2 = min(sw, x + w + 50)
                    roi_y1 = max(0, y - 150)
                    roi_y2 = min(sh, y + h + 150)
                    
                    screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                    
                    # 進行影像比對
                    res = cv2.matchTemplate(screen_roi, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    
                    print(f"  [Debug] 尋找 {img_path.name} (第 {attempt+1}/20 次) - 當前最高信心度: {max_val:.2f}")
                    
                    if max_val >= threshold:
                        abs_cx = roi_x1 + max_loc[0] + w // 2
                        abs_cy = roi_y1 + max_loc[1] + h // 2
                        print(f"[Router] 執行 {img_path.name} -> 找到浮動目標 (信心度 {max_val:.2f}) -> 點擊座標 ({abs_cx}, {abs_cy})")
                        self.controller.tap(abs_cx, abs_cy)
                        time.sleep(2.0)
                        success = True
                        break
                    else:
                        time.sleep(0.3)
                        
            if not success:
                # 建立 debug 圖片
                debug_dir = self.base_dir / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_img_path = debug_dir / f"fallback_{img_path.name}"
                
                # 畫 ROI 藍框 (BGR: 255, 0, 0)
                if screen is not None:
                    cv2.rectangle(screen, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)
                    
                    # 畫找到的最高分黃框 (BGR: 0, 255, 255)
                    abs_max_x = roi_x1 + max_loc[0]
                    abs_max_y = roi_y1 + max_loc[1]
                    cv2.rectangle(screen, (abs_max_x, abs_max_y), (abs_max_x + w, abs_max_y + h), (0, 255, 255), 2)
                    
                    # 支援 Windows 中文路徑存檔
                    is_success, im_buf_arr = cv2.imencode(".png", screen)
                    if is_success:
                        im_buf_arr.tofile(str(debug_img_path))
                
                raise ValueError(f"比對失敗！執行 {img_path.name} 找不到目標 (最高信心度 {max_val:.2f} < {threshold})。\n已將偵錯畫面存至: {debug_img_path}")
