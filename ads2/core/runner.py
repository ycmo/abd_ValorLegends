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
from src.paint_cropper import find_blue_boxes, crop_inside_blue_box
from ads2.core.close_glyph import is_close_glyph_match, match_close_glyphs
from ads2.core.close_x_classifier_runtime import CloseXClassifierRuntime
from ads2.core.click_success_collection import ClickSuccessCollector
from ads2.core.screen_collection import AdsScreenCollector
from ads2.core.geometry_close import (
    GeometryCloseSpec,
    is_geometry_close_match,
    match_geometry_close,
    match_geometry_close_rows,
)
from ads2.core.profile import AdsProfile, load_ads_profile

class AppRecoveryNeeded(Exception):
    def __init__(self, reason, screen=None):
        self.reason = reason
        self.screen = screen

class UserInterrupt(Exception):
    pass

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

# ----------------------------------------------------------------


class ReactiveRunner:
    def __init__(
        self,
        serial=None,
        ad_wait=15,
        debug=False,
        profile=None,
        geometry_close_fallback=False,
        geometry_close_threshold=0.85,
        enable_close_x_classifier=False,
        close_x_classifier_threshold=0.5,
        close_x_classifier_checkpoint=None,
        close_x_classifier_min_failures=2,
        max_classifier_fallback_taps=3,
        enable_click_success_collection=False,
        click_success_change_threshold=2.0,
        click_success_collection_dir=None,
        enable_ads_screen_collection=False,
        ads_screen_collection_dir=None,
        ads_screen_collection_min_interval=0.0,
    ):
        self.device = DeviceController(serial=serial)
        self.matcher = VisionMatcher()
        self.debug_mode = debug
        self.geometry_close_fallback = geometry_close_fallback
        self.geometry_close_spec = GeometryCloseSpec(threshold=geometry_close_threshold)
        self.enable_close_x_classifier = enable_close_x_classifier
        self.close_x_classifier_threshold = close_x_classifier_threshold
        self.close_x_classifier_min_failures = close_x_classifier_min_failures
        self.max_classifier_fallback_taps = max_classifier_fallback_taps
        self.close_x_classifier = None
        self.enable_click_success_collection = enable_click_success_collection
        self.click_success_change_threshold = click_success_change_threshold
        self.click_success_collector = None
        self.enable_ads_screen_collection = enable_ads_screen_collection
        self.ads_screen_collector = None
        self.force_esc_trigger = False
        self.profile: AdsProfile | None = None
        
        # 路徑設定
        self.base_dir = Path(__file__).parent.parent
        self.assets_dir = self.base_dir / "assets"
        self.templates_dir = self.assets_dir / "1_templates"
        self.close_icons_dir = self.templates_dir / "close_icons"
        self.close_glyphs_dir = self.templates_dir / "close_glyphs"
        self.got_icons_dir = self.templates_dir / "got_icons"
        self.free_ad_icons_dir = self.templates_dir / "free_ad_icons"
        self.scene_anchors_dir = self.templates_dir / "scene_anchors"
        self.manual_dir = self.assets_dir / "2_manual_captures"
        self.debug_errors_dir = self.assets_dir / "debug_errors"
        self.close_x_classifier_collection_dir = Path(_PROJECT_ROOT) / "close_x_classifier" / "runtime_collection"
        self.click_success_collection_dir = (
            Path(click_success_collection_dir)
            if click_success_collection_dir
            else Path(_PROJECT_ROOT) / "vision_platform" / "ads" / "runtime_collection" / "click_success"
        )
        self.ads_screen_collection_dir = (
            Path(ads_screen_collection_dir)
            if ads_screen_collection_dir
            else Path(_PROJECT_ROOT) / "vision_platform" / "ads" / "runtime_collection" / "screens"
        )
        checkpoint_path = (
            Path(close_x_classifier_checkpoint)
            if close_x_classifier_checkpoint
            else Path(_PROJECT_ROOT) / "close_x_classifier" / "runs" / "stage0_6_deployment" / "best.pt"
        )
        self.close_x_classifier_checkpoint = checkpoint_path
        if self.enable_close_x_classifier:
            self.close_x_classifier = CloseXClassifierRuntime(
                checkpoint_path=checkpoint_path,
                collection_dir=self.close_x_classifier_collection_dir,
                threshold=self.close_x_classifier_threshold,
            )
        if self.enable_click_success_collection:
            self.click_success_collector = ClickSuccessCollector(
                collection_dir=self.click_success_collection_dir,
                change_threshold=self.click_success_change_threshold,
            )
        if self.enable_ads_screen_collection:
            self.ads_screen_collector = AdsScreenCollector(
                collection_dir=self.ads_screen_collection_dir,
                min_interval_seconds=ads_screen_collection_min_interval,
            )
        self.profile = load_ads_profile(profile, project_root=Path(_PROJECT_ROOT), ads2_dir=self.base_dir)
        self.ad_wait = self.profile.ad_wait if self.profile and self.profile.ad_wait is not None else ad_wait
        
        # 確保資料夾存在
        for d in [self.close_icons_dir, self.close_glyphs_dir, self.got_icons_dir, self.free_ad_icons_dir, self.scene_anchors_dir, self.manual_dir, self.debug_errors_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.free_ad_icons_dir.mkdir(exist_ok=True)
        
        # 相容舊版：如果存在 btn_free_ad.png，自動移動到 free_ad_icons 目錄
        old_btn_path = self.templates_dir / "btn_free_ad.png"
        if old_btn_path.exists():
            shutil.move(str(old_btn_path), str(self.free_ad_icons_dir / "btn_free_ad.png"))
            
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
        print("1. 請在小畫家中用「藍色空心矩形」標示你想讓程式點擊的按鈕。")
        print("2. 畫完後按 Ctrl+S 存檔，然後直接關閉小畫家。")
        print("--------------------------------------------------")
        
        subprocess.run(["mspaint", str(edit_path)])
        
        print("⏳ [自癒系統] 偵測到小畫家已關閉，正在自動裁切藍框...")
        
        cropped_img = None
        edit_img = cv2.imdecode(np.fromfile(str(edit_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if edit_img is not None:
            boxes = find_blue_boxes(edit_img)
            if boxes:
                cropped_img = crop_inside_blue_box(edit_img, boxes[0])
                
        if cropped_img is not None and cropped_img.size > 0:
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
                print("5. 截錯了 / 誤觸 (取消)")
                
                choice = input("👉 請輸入數字 (1-5): ").strip()
                if choice == "5":
                    print("🚫 [自癒系統] 取消儲存。")
                    return
                
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
                    
                    # 截完圖當下，立刻針對當前畫面比對一次，給予即時回饋
                    test_res = self.matcher.match_template(screen, dest_path, threshold=0.1)
                    test_conf = test_res.confidence if test_res else 0.0
                    print(f"👀 [新特徵測試] 剛加入的 '{dest_path.parent.name}/{dest_path.name}' 信心度為: {test_conf:.2f}")
        else:
            print("❌ [失敗] 找不到符合的紅框，或裁切失敗。原圖已保留。")
                
        print("▶️ [自癒系統] 人機協同流程結束，恢復大迴圈...")
        print("==================================================\n")

    def sleep_or_esc(self, seconds, check_app=True):
        """可被 ESC 中斷的 sleep。如果被中斷，拋出 UserInterrupt。"""
        def do_check():
            if not check_app: return
            pkg = self.check_foreground_app()
            if pkg and pkg != "com.ageofeternity.global" and pkg != "Null":
                print(f"\n⚠️ [警告] 睡眠/等待期間偵測到跳出遊戲 (目前為: {pkg})！立刻中斷自救。")
                raise AppRecoveryNeeded(reason=pkg, screen=None)
                
        # 所有的 sleep 都先檢查
        do_check()
        
        end_time = time.time() + seconds
        last_check_time = time.time()
        while time.time() < end_time:
            if self.force_esc_trigger or keyboard.is_pressed('esc'):
                self.force_esc_trigger = True
                raise UserInterrupt()
                
            # 每睡兩秒檢查一下
            if time.time() - last_check_time >= 2.0:
                do_check()
                last_check_time = time.time()
                
            time.sleep(0.1)

    def _safe_screenshot(self):
        try:
            screen = self.device.screenshot()
            if self.ads_screen_collector is not None:
                try:
                    self.ads_screen_collector.maybe_record(
                        screen,
                        capture_reason="safe_screenshot",
                    )
                except Exception as e:
                    print(f"[AdsScreenCollection] save failed: {type(e).__name__}: {e}")
            return screen
        except Exception as e:
            print(f"\n⚠️ [警告] 截圖發生異常 ({type(e).__name__}): {e}")
            raise AppRecoveryNeeded(reason="ScreenshotError")

    def _safe_tap(self, x, y):
        try:
            self.device.tap(x, y)
        except Exception as e:
            print(f"\n⚠️ [警告] 點擊發生異常 ({type(e).__name__}): {e}")
            raise AppRecoveryNeeded(reason="TapError")

    def recover_from_app_jump(self, screen=None, reason="Unknown"):
        print(f"\n⚠️ [警告] 觸發返回遊戲機制 (原因: {reason})")
        if screen is not None:
            self.save_debug_error(screen, f"AppJump_{reason}")
        print("👉 [目前動作] 執行 Home 鍵並重新喚醒遊戲...")
        
        try:
            self.device.shell(["input", "keyevent", "3"])
        except Exception as e:
            print(f"⚠️ [警告] 執行 Home 鍵時發生錯誤: {e}")
            
        self.sleep_or_esc(1, check_app=False)
            
        try:
            self.device.shell(["monkey", "-p", "com.ageofeternity.global", "-c", "android.intent.category.LAUNCHER", "1"])
        except Exception as e:
            print(f"⚠️ [警告] 喚醒遊戲時發生錯誤 (可能已成功喚醒): {e}")
            
        self.sleep_or_esc(3, check_app=False)

    def match_profile_finish(self, screen):
        if not self.profile:
            return None
        for condition in self.profile.finish_templates:
            best_probe = None
            if self.debug_mode:
                best_probe = self.matcher.match_template(
                    screen,
                    condition.template_path,
                    threshold=0.0,
                    roi=condition.roi,
                    check_brightness=False,
                )
                best_text = "none" if best_probe is None else f"{best_probe.confidence:.3f}"
                print(
                    f"    template={condition.name} | "
                    f"threshold={condition.threshold:.3f} | "
                    f"best={best_text} | roi={condition.roi}"
                )
            result = self.matcher.match_template(
                screen,
                condition.template_path,
                threshold=condition.threshold,
                roi=condition.roi,
            )
            if result:
                return condition, result
        return None

    def _screen_change_score(self, before, after):
        if before is None or after is None:
            return 0.0
        try:
            before_small = cv2.resize(before, (160, 90), interpolation=cv2.INTER_AREA)
            after_small = cv2.resize(after, (160, 90), interpolation=cv2.INTER_AREA)
            before_gray = cv2.cvtColor(before_small, cv2.COLOR_BGR2GRAY)
            after_gray = cv2.cvtColor(after_small, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(before_gray, after_gray)
            return float(diff.mean())
        except Exception as e:
            print(f"[AdsClickCollection] screen-change check failed: {e}")
            return 0.0

    def _screen_changed(self, before, after, threshold=2.0):
        try:
            return self._screen_change_score(before, after) >= threshold
        except Exception as e:
            print(f"[CloseXClassifier] screen-change check failed: {e}")
            return False

    def _record_click_success_if_changed(
        self,
        *,
        before_screen,
        after_screen,
        click_xy,
        proposal_source,
        verified_success,
        match=None,
        extra_metadata=None,
    ):
        if self.click_success_collector is None:
            return
        metadata = dict(extra_metadata or {})
        if match is not None:
            metadata.update(
                {
                    "template_path": str(getattr(match, "template_path", "")),
                    "template_name": getattr(getattr(match, "template_path", None), "name", ""),
                    "confidence": float(getattr(match, "confidence", 0.0)),
                    "bbox": tuple(int(v) for v in getattr(match, "bbox", ())),
                    "match_center": tuple(int(v) for v in getattr(match, "center", click_xy)),
                }
            )
        try:
            record = self.click_success_collector.maybe_record(
                before_screen=before_screen,
                after_screen=after_screen,
                click_xy=(int(click_xy[0]), int(click_xy[1])),
                proposal_source=proposal_source,
                verified_success=verified_success,
                metadata=metadata,
            )
            if record is not None:
                print(f"[AdsClickCollection] saved weak success event: {record.event_dir}")
        except Exception as e:
            print(f"[AdsClickCollection] save failed: {type(e).__name__}: {e}")

    def _try_close_x_classifier_fallback(self, screen, close_roi):
        if not self.enable_close_x_classifier:
            return False, False, screen
        if self.close_x_classifier is None:
            return False, False, screen
        if not self.close_x_classifier.ready:
            print(f"[CloseXClassifier] checkpoint not found: {self.close_x_classifier_checkpoint}")
            return False, False, screen

        spec = GeometryCloseSpec(
            threshold=0.70,
            roi_top_ratio=1.0,
            max_results=8,
            max_size=52,
            max_fill=0.60,
            min_axis_union=0.55,
            min_axis_balance=0.25,
            min_length_ratio=0.80,
            gates=("white_strict", "white_soft", "black_strict", "black_soft", "cyan_strict", "bright"),
            two_stroke_fit=True,
            max_fit_error=0.42,
            max_extra_error=0.055,
            max_missing_error=0.80,
            max_center_extra_error=0.035,
        )
        rows = match_geometry_close_rows(screen, roi=close_roi, spec=spec)
        if not rows:
            print("[CloseXClassifier] no geometry candidates")
            return False, False, screen

        try:
            event = self.close_x_classifier.score_event(screen, rows)
        except Exception as e:
            print(f"[CloseXClassifier] scoring failed: {type(e).__name__}: {e}")
            return False, False, screen

        print(
            f"[CloseXClassifier] candidates={len(event.candidates)} "
            f"threshold={self.close_x_classifier_threshold:.3f} "
            f"max_taps={self.max_classifier_fallback_taps} event={event.event_dir}"
        )
        attempted = False
        tap_count = 0
        current_screen = screen
        for candidate in event.candidates:
            if candidate.p_close < self.close_x_classifier_threshold:
                continue
            if self.max_classifier_fallback_taps > 0 and tap_count >= self.max_classifier_fallback_taps:
                break
            attempted = True
            tap_count += 1
            x, y = candidate.center
            print(
                f"[CloseXClassifier] tap rank={candidate.rank} "
                f"p={candidate.p_close:.3f} geometry={candidate.geometry_score:.3f} "
                f"bbox={candidate.bbox}"
            )
            self._safe_tap(x, y)
            self.sleep_or_esc(1.0)
            after_screen = self._safe_screenshot()
            changed = self._screen_changed(current_screen, after_screen)
            self.close_x_classifier.mark_attempt(
                event,
                candidate,
                after_screen=after_screen,
                screen_changed=changed,
            )
            if changed:
                self._record_click_success_if_changed(
                    before_screen=current_screen,
                    after_screen=after_screen,
                    click_xy=(x, y),
                    proposal_source="close_x_classifier",
                    verified_success=True,
                    extra_metadata={
                        "bbox": candidate.bbox,
                        "geometry_score": candidate.geometry_score,
                        "p_close": candidate.p_close,
                        "rank": candidate.rank,
                        "classifier_event_dir": str(event.event_dir),
                    },
                )
            current_screen = after_screen if after_screen is not None else current_screen
            if changed:
                print(f"[CloseXClassifier] screen changed after rank={candidate.rank}; returning to full detection loop")
                return True, True, current_screen

        if not attempted:
            print("[CloseXClassifier] abstain: no candidate above threshold")
        else:
            print("[CloseXClassifier] all above-threshold candidates tapped; no screen change detected")
        return False, attempted, current_screen

    def run(self):
        if not self.setup():
            return
            
        print("\n==================================================")
        print("🚀 啟動無腦反應式大迴圈 (Brainless Reactive Loop)")
        print("==================================================")
        print("-> 每秒持續偵測畫面。")
        print("-> 隨時長按 [ESC] 鍵可呼叫小畫家進行自癒除錯。")
        if self.profile:
            print(f"-> 使用 profile: {self.profile.name}")
            if self.profile.description:
                print(f"-> {self.profile.description}")
        print("--------------------------------------------------")
        
        # 自訂掃描器：優先比對新圖，並在失敗時印出最高信心值
        def scan_category(paths, threshold, category_name, roi=None, source_screen=None):
            if not paths: return None
            target_screen = source_screen if source_screen is not None else screen
            # 依照修改時間排序，最新切好的圖排最前面 (優先比對)
            paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
            
            for p in paths:
                res = self.matcher.match_template(target_screen, p, threshold=threshold, roi=roi)
                if res:
                    return res
                    
            return None
        
        import threading
        def poll_esc():
            while True:
                try:
                    if keyboard.is_pressed('esc'):
                        self.force_esc_trigger = True
                except:
                    pass
                time.sleep(0.05)
        
        t = threading.Thread(target=poll_esc, daemon=True)
        t.start()
        close_template_glyph_failure_count = 0
        
        while True:
            try:
                loop_start_time = time.time()
                
                # 1. 攔截 ESC 鍵
                if self.force_esc_trigger or keyboard.is_pressed('esc'):
                    self.force_esc_trigger = False
                    raise UserInterrupt()
                    
                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 📸 截圖")
                    
                cap_start = time.time()
                screen = self._safe_screenshot()
                cap_time = time.time() - cap_start
                
                if screen is None:
                    time.sleep(1)
                    continue
                    
                matched_anything = False
                close_successful = False
                match_start = time.time()
                
                # --------------------------------------------------------
                # 重新調整優先級 (Priority)：
                # 1. Profile 結束條件 - 任務專用正常結束狀態必須優先於通用免費廣告
                # 2. 免費廣告 (free_ad_icons) - 在主畫面上點擊廣告
                # 3. 關閉按鈕 (close_icons) - 如果有未關閉的彈窗，先關掉
                # 4. 獲得道具 (got_icons) - 因為看完廣告一定會跳這個
                # 5. 主畫面錨點 (scene_anchors) - 用來判定是否已經全部看完
                # --------------------------------------------------------

                # 1. 先尋找 profile 自訂正常結束條件
                if self.debug_mode and self.profile:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [1/5] Profile 結束條件: {self.profile.name}")
                    
                profile_finish = self.match_profile_finish(screen)
                if profile_finish:
                    condition, finish_match = profile_finish
                    print(
                        f"\n✅ [Profile 結束] {condition.name} "
                        f"(信心值: {finish_match.confidence:.2f})"
                    )
                    if condition.description:
                        print(f"   {condition.description}")
                    break
                
                # 2. 尋找免費廣告 (free_ad_icons)
                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [2/5] 免費廣告: free_ad_icons")
                    
                free_ad_paths = list(self.free_ad_icons_dir.rglob("*.png"))
                free_ad_match = scan_category(free_ad_paths, 0.75, "免費廣告按鈕")
                
                if free_ad_match:
                    name = free_ad_match.template_path.name
                    print(f"\n📺 [比對成功] 找到免費廣告按鈕: '{name}' (信心值: {free_ad_match.confidence:.2f})")

                    disappeared = False
                    last_verify_screen = None
                    for i in range(1, 11):
                        before_tap_screen = last_verify_screen if last_verify_screen is not None else screen
                        tx, ty = self.get_click_point(free_ad_match, ((i - 1) % 5) + 1)
                        print(f"👉 [點擊] 執行第 {i}/10 次點擊")
                        self._safe_tap(tx, ty)
                        self.sleep_or_esc(0.5)
                        
                        v_screen = self._safe_screenshot()
                        last_verify_screen = v_screen
                        if v_screen is not None:
                            bx, by, bw, bh = free_ad_match.bbox
                            roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                            v_res = self.matcher.match_template(v_screen, free_ad_match.template_path, threshold=0.75, roi=roi)
                            if not v_res or v_res.confidence < free_ad_match.confidence - 0.10:
                                print(f"✅ [確認] 廣告按鈕在第 {i} 次點擊後已消失！")
                                self._record_click_success_if_changed(
                                    before_screen=before_tap_screen,
                                    after_screen=v_screen,
                                    click_xy=(tx, ty),
                                    proposal_source="free_ad_template",
                                    verified_success=True,
                                    match=free_ad_match,
                                    extra_metadata={"tap_index": i},
                                )
                                disappeared = True
                                break
                    
                    if disappeared:
                        print(f"⏳ [休息] 廣告播放中，進入深度休眠 {self.ad_wait} 秒...")
                        self.sleep_or_esc(self.ad_wait)
                    else:
                        print(f"\n❌ [嚴重錯誤] 免費廣告按鈕 '{name}' 連點 10 次仍無反應！")
                        raise AppRecoveryNeeded(reason=f"Stuck_ad_{name}", screen=screen)
                            
                    matched_anything = True
                    # 不回頭，重截一張最新畫面交給下一關
                    screen = self._safe_screenshot()
                    if screen is None: continue

                # 3. 尋找關閉按鈕 (close_icons)
                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [3/5] 關閉按鈕: close_icons")
                    
                close_paths = list(self.close_icons_dir.rglob("*.png"))
                h, w = screen.shape[:2]
                close_roi = (0, 0, w, int(h * 0.4))
                close_glyph_roi = close_roi
                close_match = scan_category(close_paths, 0.85, "關閉按鈕", roi=close_roi)

                if close_match is None:
                    close_match = match_close_glyphs(screen, self.close_glyphs_dir, roi=close_glyph_roi)
                template_or_glyph_close_match = close_match
                classifier_attempted = False
                if template_or_glyph_close_match is None:
                    close_template_glyph_failure_count += 1
                    if close_template_glyph_failure_count >= self.close_x_classifier_min_failures:
                        changed, classifier_attempted, screen = self._try_close_x_classifier_fallback(screen, close_roi)
                        if classifier_attempted:
                            matched_anything = True
                            close_template_glyph_failure_count = 0
                        if changed:
                            close_successful = True
                            continue

                if close_match is None and self.geometry_close_fallback and not classifier_attempted:
                    close_match = match_geometry_close(screen, roi=close_roi, spec=self.geometry_close_spec)
                    if close_match:
                        print(
                            f"\n[GeometryFallback] Found close-like X "
                            f"(score={close_match.confidence:.3f}, bbox={close_match.bbox})"
                        )

                if close_match:
                    name = close_match.template_path.name
                    print(f"\n🎯 [比對成功] 找到關閉廣告按鈕: '{name}' (信心值: {close_match.confidence:.2f})")

                    disappeared = False
                    last_verify_screen = None
                    for i in range(1, 11):
                        before_tap_screen = last_verify_screen if last_verify_screen is not None else screen
                        tx, ty = self.get_click_point(close_match, ((i - 1) % 5) + 1)
                        print(f"👉 [點擊] 執行第 {i}/10 次點擊")
                        self._safe_tap(tx, ty)
                        self.sleep_or_esc(0.5)
                        
                        v_screen = self._safe_screenshot()
                        last_verify_screen = v_screen
                        if v_screen is not None:
                            bx, by, bw, bh = close_match.bbox
                            roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                            if is_close_glyph_match(close_match):
                                v_res = match_close_glyphs(v_screen, self.close_glyphs_dir, roi=roi)
                            elif is_geometry_close_match(close_match):
                                v_res = match_geometry_close(v_screen, roi=roi, spec=self.geometry_close_spec)
                            else:
                                v_res = self.matcher.match_template(v_screen, close_match.template_path, threshold=0.85, roi=roi)
                            if not v_res or v_res.confidence < close_match.confidence - 0.10:
                                print(f"✅ [確認] 關閉按鈕在第 {i} 次點擊後已消失！")
                                if is_close_glyph_match(close_match):
                                    proposal_source = "close_glyph"
                                elif is_geometry_close_match(close_match):
                                    proposal_source = "geometry_close"
                                else:
                                    proposal_source = "close_template"
                                self._record_click_success_if_changed(
                                    before_screen=before_tap_screen,
                                    after_screen=v_screen,
                                    click_xy=(tx, ty),
                                    proposal_source=proposal_source,
                                    verified_success=True,
                                    match=close_match,
                                    extra_metadata={"tap_index": i},
                                )
                                disappeared = True
                                break
                                
                    if not disappeared:
                        print(f"\n⏭️ [跳過] 關閉按鈕 '{name}' 連點 10 次仍存在，可能卡死或誤判。")
                        self.save_debug_error(screen, f"Stuck_close_{name}")
                        if not is_geometry_close_match(close_match):
                            close_template_glyph_failure_count += 1
                            if close_template_glyph_failure_count >= self.close_x_classifier_min_failures:
                                fallback_screen = last_verify_screen if last_verify_screen is not None else screen
                                changed, classifier_attempted, screen = self._try_close_x_classifier_fallback(fallback_screen, close_roi)
                                if classifier_attempted:
                                    close_template_glyph_failure_count = 0
                                if changed:
                                    close_successful = True
                                    continue
                    else:
                        close_template_glyph_failure_count = 0
                        
                    matched_anything = True
                    close_successful = disappeared
                    # 不回頭，重截一張最新畫面交給下一關
                    screen = self._safe_screenshot()
                    if screen is None: continue

                # 4. 尋找獲得道具 (got_icons)
                if close_successful:
                    print(f"\n⏳ [轉場等待] 廣告已關閉，強制等待 3 秒讓遊戲跳出獲得道具...")
                    self.sleep_or_esc(3.0)
                    screen = self._safe_screenshot()
                    if screen is None: continue

                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [4/5] 獲得道具: got_icons")
                    
                got_paths = list(self.got_icons_dir.rglob("*.png"))
                got_match = scan_category(got_paths, 0.70, "獲得道具")
                
                if got_match:
                    name = got_match.template_path.name
                    print(f"\n🎁 [比對成功] 找到獲得道具按鈕: '{name}' (信心值: {got_match.confidence:.2f})")
                    
                    disappeared = False
                    last_verify_screen = None
                    for i in range(1, 11):
                        before_tap_screen = last_verify_screen if last_verify_screen is not None else screen
                        tx, ty = self.get_click_point(got_match, ((i - 1) % 5) + 1)
                        print(f"👉 [點擊] 執行第 {i}/10 次點擊")
                        self._safe_tap(tx, ty)
                        self.sleep_or_esc(0.5)
                        
                        v_screen = self._safe_screenshot()
                        last_verify_screen = v_screen
                        if v_screen is not None:
                            bx, by, bw, bh = got_match.bbox
                            roi = (max(0, bx-20), max(0, by-20), bw+40, bh+40)
                            v_res = self.matcher.match_template(v_screen, got_match.template_path, threshold=0.70, roi=roi)
                            if not v_res or v_res.confidence < got_match.confidence - 0.10:
                                print(f"✅ [確認] 獲得道具按鈕在第 {i} 次點擊後已消失！")
                                self._record_click_success_if_changed(
                                    before_screen=before_tap_screen,
                                    after_screen=v_screen,
                                    click_xy=(tx, ty),
                                    proposal_source="got_template",
                                    verified_success=True,
                                    match=got_match,
                                    extra_metadata={"tap_index": i},
                                )
                                disappeared = True
                                break
                                
                    if not disappeared:
                        print(f"\n⏭️ [跳過] 獲得道具 '{name}' 連點 10 次仍存在，可能卡住，繼續掃描。")
                        self.save_debug_error(screen, f"Stuck_got_{name}")
                    else:
                        print("⏳ [休息] 領取道具後，等待 0.5 秒...")
                        self.sleep_or_esc(0.5)
                        
                    matched_anything = True
                    # 不回頭，重截一張最新畫面交給下一關
                    screen = self._safe_screenshot()
                    if screen is None: continue

                # 4b. 動作後再尋找 profile 自訂正常結束條件
                if self.debug_mode and self.profile:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [4/5] Profile 結束條件: {self.profile.name}")
                    
                profile_finish = self.match_profile_finish(screen)
                if profile_finish:
                    condition, finish_match = profile_finish
                    print(
                        f"\n✅ [Profile 結束] {condition.name} "
                        f"(信心值: {finish_match.confidence:.2f})"
                    )
                    if condition.description:
                        print(f"   {condition.description}")
                    break

                # 5. 尋找主畫面錨點 (scene_anchors)
                if self.debug_mode:
                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] 🔍 [5/5] 主畫面錨點: scene_anchors")
                    
                scene_paths = list(self.scene_anchors_dir.rglob("*.png"))
                scene_match = scan_category(scene_paths, 0.75, "主畫面")
                
                if scene_match:
                    print(f"\n    🏠 [比對成功] 偵測到主畫面: '{scene_match.template_path.name}' (信心值: {scene_match.confidence:.2f})")
                    
                    # 雙重確認機制：為了防止遊戲剛關閉彈窗時，免費按鈕的進場動畫還沒跑完
                    print("⏳ [二次確認] 疑似看完全部廣告，等待 2.5 秒讓遊戲 UI 動畫跑完...")
                    self.sleep_or_esc(2.5)
                    
                    final_screen = self._safe_screenshot()
                    if final_screen is not None:
                        free_ad_paths = list(self.free_ad_icons_dir.rglob("*.png"))
                        final_free_match = scan_category(
                            free_ad_paths,
                            0.75,
                            "免費廣告按鈕(最終確認)",
                            source_screen=final_screen,
                        )
                        if final_free_match:
                            print("😅 [虛驚一場] 緩衝後發現免費廣告按鈕浮現了！繼續執行...")
                            continue
                            
                    print("🎉 [任務完成] 經過二次確認，畫面上無免費廣告按鈕，今日所有廣告已觀看完畢！")
                    break
                    
                if not matched_anything:
                    if self.debug_mode:
                        now_str = time.strftime("%H:%M:%S")
                        total_time = time.time() - loop_start_time
                        match_time = time.time() - match_start
                        print(f"[{now_str}] ⏱️ 截圖 {cap_time:.2f}s | 比對 {match_time:.2f}s | 總計 {total_time:.2f}s | 觀察中")
                    else:
                        print("👀 [觀察中] 畫面無已知特徵，等待 0.5 秒")
                    
                    self.sleep_or_esc(0.5)
            
            except AppRecoveryNeeded as e:
                self.recover_from_app_jump(screen=e.screen, reason=e.reason)
            except UserInterrupt:
                self.force_esc_trigger = False
                print("\n\n🛑 [中斷] 偵測到 ESC 按鍵！")
                screen = self._safe_screenshot()
                if screen is not None:
                    self.handle_esc_interact(screen)
                
                # 清除在小畫家期間可能累積的 ESC 觸發，避免連截兩張
                time.sleep(0.5)
                self.force_esc_trigger = False
                
        print("\n==================================================")
        print("🛑 廣告模組執行結束")
        print("==================================================")

if __name__ == "__main__":
    runner = ReactiveRunner(debug=True)
    runner.run()
