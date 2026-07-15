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
    from src.blocker_handler import BlockerHandler
    from src.config import ACTION_DEBUG_ENABLED, SHARED_ASSETS_DIR
except ImportError:
    DeviceController = None
    BlockerHandler = None
    ACTION_DEBUG_ENABLED = False
    SHARED_ASSETS_DIR = PROJECT_ROOT / "assets" / "shared"

MAX_SHARED_BACK_TAPS = 5
SHARED_BACK_THRESHOLD = 0.80
MAIN_LOBBY_THRESHOLD = 0.82
SHARED_BACK_ROI = (0, 0, 130, 100)
SHARED_BACK_RECHECK_SECONDS = 2.0
ROUTE_STEP_SUFFIXES = {".png", ".txt"}
SHARED_BACK_COMMANDS = {"shared_back", "auto_back", "back"}

class RedBoxFinder:
    def find_largest_box_info(self, img_path: Path) -> tuple[tuple[int, int], tuple[int, int, int, int], np.ndarray, str]:
        return self._find_largest_box_info(img_path, allowed_colors=("red", "green"))

    def find_largest_red_box_info(self, img_path: Path) -> tuple[tuple[int, int], tuple[int, int, int, int], np.ndarray]:
        center, rect, img, _ = self._find_largest_box_info(img_path, allowed_colors=("red",))
        return center, rect, img

    def find_largest_green_box_info(self, img_path: Path) -> tuple[tuple[int, int], tuple[int, int, int, int], np.ndarray]:
        center, rect, img, _ = self._find_largest_box_info(img_path, allowed_colors=("green",))
        return center, rect, img

    def _find_largest_box_info(
        self,
        img_path: Path,
        *,
        allowed_colors: tuple[str, ...],
    ) -> tuple[tuple[int, int], tuple[int, int, int, int], np.ndarray, str]:
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"無法讀取圖片: {img_path}")
            
        masks: list[tuple[str, np.ndarray]] = []
        if "red" in allowed_colors:
            # 嚴格抓取紅色 (雙遮罩邏輯)
            lower_red = np.array([30, 20, 230])
            upper_red = np.array([50, 40, 255])
            mask1 = cv2.inRange(img, lower_red, upper_red)
            # 容許純紅
            lower_red2 = np.array([0, 0, 240])
            upper_red2 = np.array([10, 10, 255])
            mask2 = cv2.inRange(img, lower_red2, upper_red2)
            masks.append(("red", mask1 | mask2))
        if "green" in allowed_colors:
            b, g, r = cv2.split(img)
            green_mask = ((g > 140) & (r < 100) & (b < 100) & (g > r + 50)).astype(np.uint8) * 255
            masks.append(("green", green_mask))

        best_area = 0
        best_center = None
        best_rect = None
        best_kind = None

        for kind, mask in masks:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if w < 15 or h < 15:
                    continue
                
                area = w * h
                if area > best_area:
                    # ====== 智慧去框線 ======
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
                    best_kind = kind
                
        if not best_center:
            raise ValueError(f"在 {img_path.name} 中找不到符合條件的紅框或綠框！")
            
        return best_center, best_rect, img, best_kind

class RouteNavigator:
    def __init__(
        self,
        route_name: str,
        controller=None,
        finder=None,
        base_dir=None,
        debug_actions=None,
        debug_label=None,
    ):
        self.route_name = route_name
        self.debug_actions = ACTION_DEBUG_ENABLED if debug_actions is None else bool(debug_actions)
        
        if controller is not None:
            self.controller = controller
        else:
            if DeviceController is None:
                raise ImportError("找不到 DeviceController 模組且未提供 Mock Controller。")
            self.controller = DeviceController(
                debug_actions=self.debug_actions,
                debug_label=debug_label or f"route_{self.route_name}",
            )
            if not self.controller.connect():
                raise RuntimeError("無法連線到任何可用的 ADB 裝置。")
            
        self.finder = finder if finder is not None else RedBoxFinder()
        
        if base_dir is None:
            # 預設 base_dir 為 AwayFromKeyboard/
            self.base_dir = Path(__file__).resolve().parent.parent
        else:
            self.base_dir = Path(base_dir)
            
        self.route_dir = self.base_dir / "route_screenshots" / self.route_name
        self.blocker_dir = self.base_dir / "integration_task" / "templates" / "blockers"
        self.blocker_handler = None
        if BlockerHandler is not None:
            self.blocker_handler = BlockerHandler(
                self.controller,
                template_path=self.blocker_dir / "gift_pack_label.png",
            )

    def execute_route(self, phase="enter", only_prefixes=None):
        if not self.route_dir.exists() or not self.route_dir.is_dir():
            raise FileNotFoundError(f"路由目錄不存在: {self.route_dir}")
            
        route_files = sorted(
            f
            for f in self.route_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ROUTE_STEP_SUFFIXES
        )
        if not route_files:
            raise FileNotFoundError(f"在 {self.route_dir} 中找不到任何 .png/.txt 檔案")
            
        if phase == "enter":
            target_files = [f for f in route_files if f.name[0].isdigit()]
        elif phase == "exit":
            target_files = [f for f in route_files if f.name.lower().startswith('r')]
        else:
            target_files = route_files
            
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

        grouped_items = list(grouped_files.items())
        if only_prefixes is not None:
            allowed_prefixes = {str(prefix) for prefix in only_prefixes}
            grouped_items = [
                (prefix, group)
                for prefix, group in grouped_items
                if prefix in allowed_prefixes
            ]
            if not grouped_items:
                return
            
        get_screen_func = getattr(self.controller, "get_screen", getattr(self.controller, "screenshot", None))
        
        for group_index, (prefix, group) in enumerate(grouped_items):
            command_files = [f for f in group if f.suffix.lower() == ".txt"]
            template_files = [f for f in group if f.suffix.lower() == ".png"]
            if command_files and template_files:
                names = ", ".join(f.name for f in sorted(group))
                raise ValueError(f"Route step {prefix} mixes .txt commands and .png templates: {names}")
            if command_files:
                for command_path in sorted(command_files):
                    self._execute_text_route_step(command_path, phase=phase)
                continue
            if not template_files:
                continue

            templates_info = []
            has_swipe = False
            is_optional = False
            for img_path in template_files:
                threshold = 0.5 if "_lowconf" in img_path.name.lower() else 0.7
                (cx, cy), (x, y, w, h), original_img, action_kind = self._find_route_box_info(img_path, prefer="red")
                template = original_img[y:y+h, x:x+w]
                
                name_lower = img_path.name.lower()
                is_swipe_v = "_swipev" in name_lower
                is_swipe_h = "_swipeh" in name_lower
                if is_swipe_v or is_swipe_h:
                    has_swipe = True
                if "_optional" in name_lower:
                    is_optional = True
                    
                templates_info.append({
                    "path": img_path,
                    "threshold": threshold,
                    "cx": cx, "cy": cy, "x": x, "y": y, "w": w, "h": h,
                    "template": template,
                    "action_kind": action_kind,
                    "verify_next": "_verifynext" in img_path.stem.lower(),
                    "verify_disappear": "_verify" in img_path.stem.lower() and "_verifynext" not in img_path.stem.lower(),
                    "is_swipe_v": is_swipe_v,
                    "is_swipe_h": is_swipe_h
                })

            next_templates_info = []
            if group_index + 1 < len(grouped_items):
                _, next_group = grouped_items[group_index + 1]
                for next_img_path in next_group:
                    if next_img_path.suffix.lower() != ".png":
                        continue
                    threshold = 0.5 if "_lowconf" in next_img_path.name.lower() else 0.7
                    (cx, cy), (x, y, w, h), original_img, action_kind = self._find_route_box_info(next_img_path, prefer="green")
                    next_templates_info.append({
                        "path": next_img_path,
                        "threshold": threshold,
                        "cx": cx, "cy": cy, "x": x, "y": y, "w": w, "h": h,
                        "template": original_img[y:y+h, x:x+w],
                        "action_kind": action_kind,
                    })
                
            if get_screen_func is None:
                if templates_info[0]["action_kind"] != "red":
                    print(f"[Fallback] 無法取得實機畫面 -> 綠框 Anchor {templates_info[0]['path'].name} 視為通過")
                    continue
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
            
            attempts_phase1 = 12 if is_optional else (3 if has_swipe else 20)
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
                        if t_info["verify_next"]:
                            success = self._tap_and_verify_next(
                                get_screen_func,
                                phase=phase,
                                t_info=t_info,
                                next_templates_info=next_templates_info,
                                roi=(roi_x1, roi_x2, roi_y1, roi_y2),
                                match_loc=max_loc,
                                confidence=max_val,
                            )
                        elif t_info["verify_disappear"]:
                            success = self._tap_and_verify_disappearance(
                                get_screen_func,
                                phase=phase,
                                t_info=t_info,
                                roi=(roi_x1, roi_x2, roi_y1, roi_y2),
                                match_loc=max_loc,
                                confidence=max_val,
                            )
                        elif t_info["action_kind"] == "red":
                            self._tap_route_target(
                                abs_cx,
                                abs_cy,
                                phase=phase,
                                template_name=t_info["path"].name,
                                confidence=max_val,
                                bbox=(roi_x1 + max_loc[0], roi_y1 + max_loc[1], w, h),
                            )
                            time.sleep(2.0)
                            success = True
                        else:
                            print(f"[Router] {t_info['path'].name} 是綠框 Anchor，確認出現後不點擊")
                            success = True
                        break
                        
                if success:
                    break
                else:
                    if self._handle_blocking_popup(screen):
                        continue
                    if not has_swipe:
                        time.sleep(0.3)
                        
            if not success and is_optional and not has_swipe:
                failed_name = best_overall_img.name if best_overall_img else prefix
                if self.debug_actions:
                    debug_img_path = self._save_match_failure_debug(
                        screen,
                        failed_name,
                        best_overall_roi,
                        best_overall_loc,
                        best_overall_w,
                        best_overall_h,
                    )
                    print(f"[Router] optional miss debug saved: {debug_img_path}")
                print(f"[Router] 步驟群組 {prefix} 帶有 _optional 標籤，找不到目標，自動跳過該步驟...")
                continue

            if not success and has_swipe and screen is not None:
                print(f"  [Debug] 群組 {prefix} 階段一尋找失敗 (最高信心度 {best_overall_val:.2f})，準備動態滑動...")
                swipe_t = next(t for t in templates_info if t["is_swipe_v"] or t["is_swipe_h"])
                cx_orig = swipe_t["x"] + swipe_t["w"] // 2
                cy_orig = swipe_t["y"] + swipe_t["h"] // 2
                sh, sw = screen.shape[:2]
                
                for swipe_dir in [1, -1]:
                    if swipe_dir == 1:
                        print("  [Debug] 準備動態滑動 (方向：正向)...")
                        swipe_count = 1
                    else:
                        print("  [Debug] 正向滑動尋找失敗，準備反向滑動救援...")
                        swipe_count = 2
                        
                    for _ in range(swipe_count):
                        if swipe_t["is_swipe_v"]:
                            swipe_x, y_start, _, y_end, duration_ms = self._dynamic_swipe_points(
                                swipe_t,
                                screen_width=sw,
                                screen_height=sh,
                                swipe_dir=swipe_dir,
                            )
                            self.controller.swipe(swipe_x, y_start, swipe_x, y_end, duration_ms=duration_ms)
                        else:
                            x_start = (3 * sw // 4) if swipe_dir == 1 else (sw // 4)
                            x_end = (sw // 4) if swipe_dir == 1 else (3 * sw // 4)
                            self.controller.swipe(x_start, cy_orig, x_end, cy_orig, duration_ms=400)
                        time.sleep(0.5)
                        
                    time.sleep(1.0)
                    
                    for attempt in range(5):
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
                            
                            print(f"  [Debug] 滑動後尋找 {t_info['path'].name} (第 {attempt+1}/5 次) - 當前最高信心度: {max_val:.2f}")
                            
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
                                if t_info["verify_next"]:
                                    success = self._tap_and_verify_next(
                                        get_screen_func,
                                        phase=phase,
                                        t_info=t_info,
                                        next_templates_info=next_templates_info,
                                        roi=(roi_x1, roi_x2, roi_y1, roi_y2),
                                        match_loc=max_loc,
                                        confidence=max_val,
                                    )
                                elif t_info["verify_disappear"]:
                                    success = self._tap_and_verify_disappearance(
                                        get_screen_func,
                                        phase=phase,
                                        t_info=t_info,
                                        roi=(roi_x1, roi_x2, roi_y1, roi_y2),
                                        match_loc=max_loc,
                                        confidence=max_val,
                                    )
                                elif t_info["action_kind"] == "red":
                                    self._tap_route_target(
                                        abs_cx,
                                        abs_cy,
                                        phase=phase,
                                        template_name=t_info["path"].name,
                                        confidence=max_val,
                                        bbox=(roi_x1 + max_loc[0], roi_y1 + max_loc[1], w, h),
                                    )
                                    time.sleep(2.0)
                                    success = True
                                else:
                                    print(f"[Router] {t_info['path'].name} 是綠框 Anchor，確認出現後不點擊")
                                    success = True
                                break
                                
                        if success:
                            break
                        else:
                            if self._handle_blocking_popup(screen):
                                continue
                            time.sleep(0.3)
                            
                    if success:
                        break
                        
            if not success and is_optional:
                failed_name = best_overall_img.name if best_overall_img else prefix
                if self.debug_actions:
                    debug_img_path = self._save_match_failure_debug(
                        screen,
                        failed_name,
                        best_overall_roi,
                        best_overall_loc,
                        best_overall_w,
                        best_overall_h,
                    )
                    print(f"[Router] optional miss debug saved: {debug_img_path}")
                print(f"[Router] optional step group {prefix} was not found; skipping.")
                continue

            if not success:
                failed_name = best_overall_img.name if best_overall_img else prefix

                debug_img_path = self._save_match_failure_debug(
                    screen,
                    failed_name,
                    best_overall_roi,
                    best_overall_loc,
                    best_overall_w,
                    best_overall_h,
                )
                raise ValueError(f"比對失敗！步驟群組 {prefix} 找不到目標 (最高信心度 {best_overall_val:.2f} < {best_overall_threshold})。\n已將偵錯畫面存至: {debug_img_path}")

    def _execute_text_route_step(self, command_path: Path, *, phase: str) -> None:
        command = self._read_text_route_command(command_path)
        if command not in SHARED_BACK_COMMANDS:
            raise ValueError(f"Unsupported route command in {command_path.name}: {command}")

        self._auto_return_to_main(command_path, phase=phase)

    def _read_text_route_command(self, command_path: Path) -> str:
        text = command_path.read_text(encoding="utf-8-sig")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            return line.replace("=", " ").split()[0].strip().lower()
        raise ValueError(f"Empty route command file: {command_path.name}")

    def _auto_return_to_main(self, command_path: Path, *, phase: str) -> None:
        get_screen_func = getattr(self.controller, "get_screen", getattr(self.controller, "screenshot", None))
        if get_screen_func is None:
            raise ValueError(f"{command_path.name} requires screenshot support for shared back")

        back_taps = 0
        checks = 0
        max_checks = MAX_SHARED_BACK_TAPS * 3 + 1
        while back_taps <= MAX_SHARED_BACK_TAPS and checks < max_checks:
            checks += 1
            screen = get_screen_func()
            if screen is None:
                continue
            if self._is_main_lobby_visible(screen):
                print(f"[Router] {command_path.name}: reached main lobby")
                return

            if back_taps >= MAX_SHARED_BACK_TAPS:
                break

            match = self._match_shared_back_button(screen)
            if match is not None:
                x, y, w, h = match["bbox"]
                self._tap_route_target(
                    *match["center"],
                    phase=phase,
                    template_name=match["asset"].name,
                    confidence=match["confidence"],
                    bbox=(x, y, w, h),
                )
                back_taps += 1
                time.sleep(SHARED_BACK_RECHECK_SECONDS)
                continue

            if self._handle_blocking_popup(screen):
                time.sleep(1.0)
                continue

            print(
                f"[Router] {command_path.name}: main/back not visible "
                f"(check {checks}/{max_checks}); waiting for transition"
            )
            time.sleep(SHARED_BACK_RECHECK_SECONDS)

        screen = get_screen_func()
        debug_img_path = self._save_match_failure_debug(
            screen,
            command_path.name,
            None,
            None,
            0,
            0,
        )
        raise ValueError(f"{command_path.name}: failed to reach main lobby after {MAX_SHARED_BACK_TAPS} shared back taps; debug={debug_img_path}")

    def _is_main_lobby_visible(self, screen: np.ndarray) -> bool:
        for asset in sorted(SHARED_ASSETS_DIR.glob("main_lobby_anchor*.png")):
            if self._match_asset(screen, asset, MAIN_LOBBY_THRESHOLD) is not None:
                return True
        return False

    def _match_shared_back_button(self, screen: np.ndarray):
        assets = sorted((SHARED_ASSETS_DIR / "back_buttons").glob("*.png"))
        best = None
        for asset in assets:
            match = self._match_asset(
                screen,
                asset,
                SHARED_BACK_THRESHOLD,
                roi=SHARED_BACK_ROI,
            )
            if match is None:
                continue
            if best is None or match["confidence"] > best["confidence"]:
                best = match
        return best

    def _match_asset(self, screen: np.ndarray, asset_path: Path, threshold: float, roi=None):
        if screen is None or not asset_path.exists():
            return None
        template = cv2.imdecode(np.fromfile(asset_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            return None

        sh, sw = screen.shape[:2]
        if roi is None:
            roi_x, roi_y, roi_w, roi_h = 0, 0, sw, sh
        else:
            roi_x, roi_y, roi_w, roi_h = roi
            roi_x = max(0, roi_x)
            roi_y = max(0, roi_y)
            roi_w = max(0, min(roi_w, sw - roi_x))
            roi_h = max(0, min(roi_h, sh - roi_y))
        search = screen[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
        th, tw = template.shape[:2]
        if search.size == 0 or th > search.shape[0] or tw > search.shape[1]:
            return None

        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, loc = cv2.minMaxLoc(result)
        if confidence < threshold:
            return None

        x = roi_x + loc[0]
        y = roi_y + loc[1]
        return {
            "asset": asset_path,
            "confidence": confidence,
            "bbox": (x, y, tw, th),
            "center": (x + tw // 2, y + th // 2),
        }

    def _find_route_box_info(self, img_path: Path, *, prefer: str = "red"):
        if prefer == "green":
            find_green = getattr(self.finder, "find_largest_green_box_info", None)
            if find_green is not None:
                try:
                    center, rect, img = find_green(img_path)
                    return center, rect, img, "green"
                except ValueError:
                    pass

        red_error = None
        try:
            center, rect, img = self.finder.find_largest_red_box_info(img_path)
            return center, rect, img, "red"
        except ValueError as exc:
            red_error = exc
            if prefer == "red":
                find_green = getattr(self.finder, "find_largest_green_box_info", None)
                if find_green is not None:
                    center, rect, img = find_green(img_path)
                    return center, rect, img, "green"

        find_any = getattr(self.finder, "find_largest_box_info", None)
        if find_any is not None:
            return find_any(img_path)
        if red_error is not None:
            raise red_error
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的框！")

    def _dynamic_swipe_points(self, swipe_t, *, screen_width: int, screen_height: int, swipe_dir: int):
        roi_x1 = max(0, swipe_t["x"] - 50)
        roi_x2 = min(screen_width, swipe_t["x"] + swipe_t["w"] + 50)
        swipe_x = (roi_x1 + roi_x2) // 2
        y_start = (3 * screen_height // 4) if swipe_dir == 1 else (screen_height // 4)
        y_end = (screen_height // 4) if swipe_dir == 1 else (3 * screen_height // 4)
        return swipe_x, y_start, swipe_x, y_end, 700

    def _tap_route_target(
        self,
        x: int,
        y: int,
        *,
        phase: str,
        template_name: str,
        confidence: float,
        bbox: tuple[int, int, int, int],
    ) -> None:
        annotate = getattr(self.controller, "annotate_next_tap_debug", None)
        if annotate is not None:
            annotate(
                lines=[
                    f"router route={self.route_name} phase={phase}",
                    f"template={template_name} confidence={confidence:.3f}",
                ],
                boxes=[(*bbox, "route_match")],
            )
        self.controller.tap(x, y)

    def _tap_and_verify_disappearance(
        self,
        get_screen_func,
        *,
        phase: str,
        t_info: dict,
        roi: tuple[int, int, int, int],
        match_loc: tuple[int, int],
        confidence: float,
    ) -> bool:
        roi_x1, roi_x2, roi_y1, roi_y2 = roi
        w, h = t_info["w"], t_info["h"]
        current_loc = match_loc
        current_confidence = confidence

        for click_attempt in range(1, 4):
            abs_x = roi_x1 + current_loc[0]
            abs_y = roi_y1 + current_loc[1]
            self._tap_route_target(
                abs_x + w // 2,
                abs_y + h // 2,
                phase=phase,
                template_name=t_info["path"].name,
                confidence=current_confidence,
                bbox=(abs_x, abs_y, w, h),
            )

            for verify_attempt in range(1, 4):
                time.sleep(0.5)
                screen = get_screen_func()
                if screen is None:
                    continue
                screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
                result = cv2.matchTemplate(screen_roi, t_info["template"], cv2.TM_CCOEFF_NORMED)
                _, current_confidence, _, current_loc = cv2.minMaxLoc(result)
                print(
                    f"  [Verify] {t_info['path'].name} click={click_attempt}/3 "
                    f"check={verify_attempt}/3 confidence={current_confidence:.2f}"
                )
                if current_confidence < t_info["threshold"]:
                    print(f"[Router] 驗證成功：{t_info['path'].name} 已消失")
                    return True

            print(
                f"[Router] 驗證未通過：{t_info['path'].name} 仍存在 "
                f"(confidence={current_confidence:.2f})"
            )

        raise ValueError(
            f"點擊後驗證失敗：{t_info['path'].name} 經 3 次點擊後仍未消失 "
            f"(confidence={current_confidence:.2f})"
        )

    def _tap_and_verify_next(
        self,
        get_screen_func,
        *,
        phase: str,
        t_info: dict,
        next_templates_info: list[dict],
        roi: tuple[int, int, int, int],
        match_loc: tuple[int, int],
        confidence: float,
    ) -> bool:
        if not next_templates_info:
            raise ValueError(f"{t_info['path'].name} 使用 _verifyNext，但後面沒有下一個步驟可驗證")

        roi_x1, _, roi_y1, _ = roi
        w, h = t_info["w"], t_info["h"]
        current_loc = match_loc
        current_confidence = confidence

        for click_attempt in range(1, 4):
            abs_x = roi_x1 + current_loc[0]
            abs_y = roi_y1 + current_loc[1]
            self._tap_route_target(
                abs_x + w // 2,
                abs_y + h // 2,
                phase=phase,
                template_name=t_info["path"].name,
                confidence=current_confidence,
                bbox=(abs_x, abs_y, w, h),
            )

            for verify_attempt in range(1, 7):
                time.sleep(0.5)
                screen = get_screen_func()
                if screen is None:
                    continue
                matched_next = self._match_any_route_template(screen, next_templates_info)
                best_name, best_confidence = matched_next["name"], matched_next["confidence"]
                print(
                    f"  [VerifyNext] {t_info['path'].name} click={click_attempt}/3 "
                    f"check={verify_attempt}/6 next={best_name} confidence={best_confidence:.2f}"
                )
                if matched_next["matched"]:
                    print(f"[Router] 驗證成功：下一步 {best_name} 已出現")
                    return True

            print(f"[Router] 下一步未出現，準備重新點擊 {t_info['path'].name}")

        raise ValueError(f"點擊後驗證失敗：{t_info['path'].name} 經 3 次點擊後下一步仍未出現")

    def _match_any_route_template(self, screen: np.ndarray, templates_info: list[dict]) -> dict:
        sh, sw = screen.shape[:2]
        best = {
            "matched": False,
            "name": templates_info[0]["path"].name if templates_info else "",
            "confidence": 0.0,
        }
        for t_info in templates_info:
            x, y, w, h = t_info["x"], t_info["y"], t_info["w"], t_info["h"]
            roi_x1 = max(0, x - 50)
            roi_x2 = min(sw, x + w + 50)
            roi_y1 = max(0, y - 150)
            roi_y2 = min(sh, y + h + 150)
            screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
            result = cv2.matchTemplate(screen_roi, t_info["template"], cv2.TM_CCOEFF_NORMED)
            _, confidence, _, _ = cv2.minMaxLoc(result)
            if confidence > best["confidence"]:
                best = {
                    "matched": confidence >= t_info["threshold"],
                    "name": t_info["path"].name,
                    "confidence": confidence,
                }
        return best

    def _save_match_failure_debug(
        self,
        screen,
        failed_name,
        best_overall_roi,
        best_overall_loc,
        best_overall_w,
        best_overall_h,
    ) -> Path:
        debug_dir = self.base_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        failed_path = Path(str(failed_name))
        debug_name = f"fallback_{failed_name}" if failed_path.suffix.lower() == ".png" else f"fallback_{failed_path.stem}.png"
        debug_img_path = debug_dir / debug_name

        if screen is not None:
            debug_image = screen.copy()
            if best_overall_roi is not None and best_overall_loc is not None:
                roi_x1, roi_x2, roi_y1, roi_y2 = best_overall_roi
                cv2.rectangle(debug_image, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)
                abs_max_x = roi_x1 + best_overall_loc[0]
                abs_max_y = roi_y1 + best_overall_loc[1]
                cv2.rectangle(
                    debug_image,
                    (abs_max_x, abs_max_y),
                    (abs_max_x + best_overall_w, abs_max_y + best_overall_h),
                    (0, 255, 255),
                    2,
                )
            is_success, im_buf_arr = cv2.imencode(".png", debug_image)
            if is_success:
                im_buf_arr.tofile(str(debug_img_path))
        return debug_img_path

    def _handle_blocking_popup(self, screen: np.ndarray) -> bool:
        """Close known temporary popups that block route target recognition."""
        if self.blocker_handler is None:
            return False
        return self.blocker_handler.handle_known_blocker(screen)

    def handle_blocking_popup(self, screen: np.ndarray | None = None) -> bool:
        """Public recovery hook for callers whose post-route screen is blocked."""
        if screen is None:
            get_screen = getattr(
                self.controller,
                "get_screen",
                getattr(self.controller, "screenshot", None),
            )
            if get_screen is None:
                return False
            screen = get_screen()
        return self._handle_blocking_popup(screen)
