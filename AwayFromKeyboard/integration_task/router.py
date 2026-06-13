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
            
        import re
        from collections import defaultdict
        
        grouped_files = defaultdict(list)
        for f in target_files:
            match = re.match(r'^([a-zA-Z]*\d+)', f.name)
            if match:
                prefix = match.group(1)
            else:
                prefix = f.name
            grouped_files[prefix].append(f)
            
        get_screen_func = getattr(self.controller, "get_screen", getattr(self.controller, "screenshot", None))
        
        for prefix, group in grouped_files.items():
            templates_info = []
            has_swipe = False
            for img_path in group:
                threshold = 0.5 if "_lowconf" in img_path.name.lower() else 0.7
                (cx, cy), (x, y, w, h), original_img = self.finder.find_largest_red_box_info(img_path)
                template = original_img[y:y+h, x:x+w]
                
                name_lower = img_path.name.lower()
                is_swipe_v = "_swipev" in name_lower
                is_swipe_h = "_swipeh" in name_lower
                if is_swipe_v or is_swipe_h:
                    has_swipe = True
                    
                templates_info.append({
                    "path": img_path,
                    "threshold": threshold,
                    "cx": cx, "cy": cy, "x": x, "y": y, "w": w, "h": h,
                    "template": template,
                    "is_swipe_v": is_swipe_v,
                    "is_swipe_h": is_swipe_h
                })
                
            if get_screen_func is None:
                cx, cy = templates_info[0]["cx"], templates_info[0]["cy"]
                print(f"[Fallback] 無法取得實機畫面 -> 退回點擊原始紅框中心 ({cx}, {cy})")
                self.controller.tap(cx, cy)
                time.sleep(2.0)
                continue
                
            success = False
            best_overall_val = 0.0
            best_overall_loc = None
            best_overall_img = None
            best_overall_w = 0
            best_overall_h = 0
            best_overall_roi = None
            best_overall_threshold = 0.7
            
            attempts_phase1 = 1 if has_swipe else 20
            screen = None
            
            for attempt in range(attempts_phase1):
                screen = get_screen_func()
                if screen is None:
                    continue
                sh, sw = screen.shape[:2]
                
                for t_info in templates_info:
                    x, y, w, h = t_info["x"], t_info["y"], t_info["w"], t_info["h"]
                    if t_info["is_swipe_v"]:
                        roi_x1 = max(0, x - 50)
                        roi_x2 = min(sw, x + w + 50)
                        roi_y1 = 0
                        roi_y2 = sh
                    elif t_info["is_swipe_h"]:
                        roi_x1 = 0
                        roi_x2 = sw
                        roi_y1 = max(0, y - 150)
                        roi_y2 = min(sh, y + h + 150)
                    else:
                        roi_x1 = max(0, x - 50)
                        roi_x2 = min(sw, x + w + 50)
                        roi_y1 = max(0, y - 150)
                        roi_y2 = min(sh, y + h + 150)
                        
                    screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                    res = cv2.matchTemplate(screen_roi, t_info["template"], cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    
                    if not has_swipe:
                        print(f"  [Debug] 尋找 {t_info['path'].name} (第 {attempt+1}/{attempts_phase1} 次) - 當前最高信心度: {max_val:.2f}")
                    
                    if max_val > best_overall_val:
                        best_overall_val = max_val
                        best_overall_loc = max_loc
                        best_overall_img = t_info["path"]
                        best_overall_w = w
                        best_overall_h = h
                        best_overall_roi = (roi_x1, roi_x2, roi_y1, roi_y2)
                        best_overall_threshold = t_info["threshold"]
                        
                    if max_val >= t_info["threshold"]:
                        abs_cx = roi_x1 + max_loc[0] + w // 2
                        abs_cy = roi_y1 + max_loc[1] + h // 2
                        print(f"[Router] 執行 {t_info['path'].name} -> 找到浮動目標 (信心度 {max_val:.2f}) -> 點擊座標 ({abs_cx}, {abs_cy})")
                        self.controller.tap(abs_cx, abs_cy)
                        time.sleep(2.0)
                        success = True
                        break
                        
                if success:
                    break
                else:
                    if not has_swipe:
                        time.sleep(0.3)
                        
            if not success and has_swipe and screen is not None:
                print(f"  [Debug] 群組 {prefix} 階段一尋找失敗 (最高信心度 {best_overall_val:.2f})，準備動態滑動...")
                swipe_t = next(t for t in templates_info if t["is_swipe_v"] or t["is_swipe_h"])
                cx_orig = swipe_t["x"] + swipe_t["w"] // 2
                cy_orig = swipe_t["y"] + swipe_t["h"] // 2
                sh, sw = screen.shape[:2]
                
                if swipe_t["is_swipe_v"]:
                    start_y = min(sh - 10, cy_orig + 150)
                    end_y = max(10, cy_orig - 150)
                    self.controller.swipe(cx_orig, start_y, cx_orig, end_y, duration_ms=500)
                else:
                    start_x = min(sw - 10, cx_orig + 150)
                    end_x = max(10, cx_orig - 150)
                    self.controller.swipe(start_x, cy_orig, end_x, cy_orig, duration_ms=500)
                    
                time.sleep(1.5)
                
                for attempt in range(10):
                    screen = get_screen_func()
                    if screen is None:
                        continue
                    sh, sw = screen.shape[:2]
                    
                    for t_info in templates_info:
                        x, y, w, h = t_info["x"], t_info["y"], t_info["w"], t_info["h"]
                        if t_info["is_swipe_v"]:
                            roi_x1 = max(0, x - 50)
                            roi_x2 = min(sw, x + w + 50)
                            roi_y1 = 0
                            roi_y2 = sh
                        elif t_info["is_swipe_h"]:
                            roi_x1 = 0
                            roi_x2 = sw
                            roi_y1 = max(0, y - 150)
                            roi_y2 = min(sh, y + h + 150)
                        else:
                            roi_x1 = max(0, x - 50)
                            roi_x2 = min(sw, x + w + 50)
                            roi_y1 = max(0, y - 150)
                            roi_y2 = min(sh, y + h + 150)
                            
                        screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                        res = cv2.matchTemplate(screen_roi, t_info["template"], cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        
                        print(f"  [Debug] 滑動後尋找 {t_info['path'].name} (第 {attempt+1}/10 次) - 當前最高信心度: {max_val:.2f}")
                        
                        if max_val > best_overall_val:
                            best_overall_val = max_val
                            best_overall_loc = max_loc
                            best_overall_img = t_info["path"]
                            best_overall_w = w
                            best_overall_h = h
                            best_overall_roi = (roi_x1, roi_x2, roi_y1, roi_y2)
                            best_overall_threshold = t_info["threshold"]
                            
                        if max_val >= t_info["threshold"]:
                            abs_cx = roi_x1 + max_loc[0] + w // 2
                            abs_cy = roi_y1 + max_loc[1] + h // 2
                            print(f"[Router] 滑動後執行 {t_info['path'].name} -> 找到浮動目標 (信心度 {max_val:.2f}) -> 點擊座標 ({abs_cx}, {abs_cy})")
                            self.controller.tap(abs_cx, abs_cy)
                            time.sleep(2.0)
                            success = True
                            break
                            
                    if success:
                        break
                    else:
                        time.sleep(0.3)
                        
            if not success:
                debug_dir = self.base_dir / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                failed_name = best_overall_img.name if best_overall_img else prefix
                debug_img_path = debug_dir / f"fallback_{failed_name}"
                
                if screen is not None and best_overall_roi is not None and best_overall_loc is not None:
                    roi_x1, roi_x2, roi_y1, roi_y2 = best_overall_roi
                    cv2.rectangle(screen, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)
                    abs_max_x = roi_x1 + best_overall_loc[0]
                    abs_max_y = roi_y1 + best_overall_loc[1]
                    cv2.rectangle(screen, (abs_max_x, abs_max_y), (abs_max_x + best_overall_w, abs_max_y + best_overall_h), (0, 255, 255), 2)
                    is_success, im_buf_arr = cv2.imencode(".png", screen)
                    if is_success:
                        im_buf_arr.tofile(str(debug_img_path))
                
                raise ValueError(f"比對失敗！步驟群組 {prefix} 找不到目標 (最高信心度 {best_overall_val:.2f} < {best_overall_threshold})。\n已將偵錯畫面存至: {debug_img_path}")
