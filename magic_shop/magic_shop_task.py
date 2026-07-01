from __future__ import annotations

import time
import sys
import cv2
import numpy as np
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SHARED_ASSETS_DIR, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.task_runner import BaseTask
from src.exceptions import TaskFailedError
from src.ocr_utils import get_cached_easyocr_reader, read_texts_easyocr, parse_power_value
from src.vision_matcher import read_image

class MagicShopTask(BaseTask):
    spec = TASK_SPECS["magic_shop"]
    required_assets = (
        "紫珠960k.png",
        "競技場券480k.png",
        "金牌5000k.png",
        "英雄碎片1800k.png",
        "商品圖片/紫珠800.png",
        "商品圖片/競技場券5.png",
        "商品圖片/金牌10.png",
        "商品圖片/英雄碎片30.png",
        "購買.png",
        "獲得道具.png",
        "是.png",
        "back_arrow.png",
        "刷新100.png",
        "刷新200.png",
    )
    BACK_ARROW_ROI = (0, 0, 100, 80)
    SHOP_ITEM_ROI = (250, 100, 710, 440)
    SHOP_SCAN_VIEWS = 3
    SHOP_SWIPE = (480, 450, 480, 150, 900)
    SHOP_SETTLE_SECONDS = 1.0
    ITEM_COLUMN_ROIS = {
        "left": (280, 100, 145, 440),
        "middle": (430, 100, 145, 440),
        "right_middle": (580, 100, 145, 440),
    }

    def asset_path(self, name: str, source: str = "task") -> Path:
        if source == "shared":
            from src.config import SHARED_ASSETS_DIR
            return SHARED_ASSETS_DIR / name
        return Path(__file__).parent / "assets" / name

    def missing_assets(self) -> tuple[Path, ...]:
        missing = []
        for path in (self.spec.task_label_asset, SHARED_ASSETS_DIR / "go_button.png"):
            if not path.exists():
                missing.append(path)
        for name in self.required_assets:
            path = self.asset_path(name)
            if not path.exists():
                missing.append(path)
        return tuple(missing)

    def is_task_scene(self, screen) -> bool:
        back_arrow = self.context.matcher.match_template(
            screen,
            self.asset_path("back_arrow.png"),
            threshold=0.82,
            roi=self.BACK_ARROW_ROI,
        )
        if back_arrow is None:
            return False

        for name in ("紫珠960k.png", "競技場券480k.png", "金牌5000k.png", "英雄碎片1800k.png"):
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(name),
                threshold=0.60,
                roi=self.SHOP_ITEM_ROI,
            )
            if match is not None:
                return True
        return False

    TARGET_ITEM_TEMPLATES = (
        ("960k", "商品圖片/紫珠800.png", "紫珠960k.png", "left"),
        ("480k", "商品圖片/競技場券5.png", "競技場券480k.png", "middle"),
        ("5000k", "商品圖片/金牌10.png", "金牌5000k.png", "right_middle"),
        ("1800k", "商品圖片/英雄碎片30.png", "英雄碎片1800k.png", "middle"),
    )
    ITEM_TEMPLATE_THRESHOLD = 0.60
    ITEM_ICON_THRESHOLD = 0.80
    ITEM_PRICE_VERIFY_THRESHOLD = 0.85
    ITEM_PRICE_ONLY_FALLBACKS = {
        "480k": 0.98,
    }
    ITEM_CLUSTER_DISTANCE = 48
    ITEM_PRICE_ROI_OFFSET = (-85, 55, 170, 65)
    REFRESH_BUTTON_ROI = (700, 40, 220, 90)
    REFRESH_TEMPLATE_THRESHOLD = 0.82
    REFRESH_TEMPLATE_MARGIN = 0.03
    REFRESH_TEMPLATE_DIGIT_CROP_X = 45

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            print("  ⏳ 正在初始化 OCR 引擎載入模型 (初次啟動需要幾秒鐘，請稍候)...")
            self._ocr_reader = get_cached_easyocr_reader(("en",), download_enabled=False)
            print("  ✅ OCR 引擎初始化完成！")
        return self._ocr_reader

    def get_current_coins(self, screen) -> int:
        # 假設金幣在畫面右上角，取 y=0~80, x=400~960
        roi = (400, 0, 560, 80)
        fragments = read_texts_easyocr(screen, roi=roi, reader=self._get_ocr_reader())

        print(f"  [OCR] 偵測到的文字片段: {fragments}")

        max_val = -1
        for frag in fragments:
            text = str(frag['text']).lower().replace(',', '').replace(' ', '')

            # 如果有 M，例如 12.3m 或 12m
            if 'm' in text:
                import re
                match = re.search(r"(\d+(?:\.\d+)?)m", text)
                if match:
                    val = float(match.group(1)) * 1000  # 轉成 k
                    max_val = max(max_val, int(val))
                    continue

            # 處理 k 或一般數字
            val = parse_power_value(text)
            if val > max_val:
                max_val = val

        return max_val

    def buy_items_on_screen(self, dry_run: bool = False, ignore_boxes: list = None) -> int:
        bought_count = 0
        screen = self.context.controller.screenshot()
        candidates = self._find_buyable_item_candidates(screen)
        print(f"  [比對] 本次掃描找到 {len(candidates)} 個亮著的目標商品。")

        for text, template_name, match in candidates:
            roi_x, roi_y, roi_w, roi_h = self._expanded_roi_around_bbox(screen, match.bbox)
            print(f"  -> [比對] {text} template={template_name} confidence={match.confidence:.3f}")

            if dry_run:
                self._save_dry_run_template_debug(screen, text, match)
                continue

            while True:
                fresh_screen = self.context.controller.screenshot()
                fresh_match = self.context.matcher.match_template(
                    fresh_screen,
                    self.asset_path(template_name),
                    threshold=self.ITEM_TEMPLATE_THRESHOLD,
                    roi=(roi_x, roi_y, roi_w, roi_h),
                )
                if fresh_match is None:
                    print(f"    {text} 目前已不是亮著的可買狀態，跳過。")
                    break

                self.context.controller.tap(*fresh_match.center)
                time.sleep(1.0)

                print("  [等待中] 正在尋找「購買確認」按鈕...")
                buy_btn_path = self.asset_path("購買.png")
                buy_match = None
                if buy_btn_path.exists():
                    buy_screen = self.context.controller.screenshot()
                    buy_match = self.context.matcher.match_template(buy_screen, buy_btn_path, threshold=0.82)

                if buy_match is None:
                    print(f"    點擊了 {text} 但沒有出現購買按鈕，可能已售罄。")
                    break

                self.context.controller.tap(*buy_match.center)
                print("    點擊了購買按鈕。")
                time.sleep(1.5)

                print("  [檢查中] 檢查是否有獲得道具的關閉視窗...")
                reward_path = self.asset_path("獲得道具.png")
                if reward_path.exists():
                    reward_match = self.context.matcher.match_template(
                        self.context.controller.screenshot(),
                        reward_path,
                        threshold=0.82,
                    )
                    if reward_match is not None:
                        self.context.controller.tap(*reward_match.center)
                        print("    點擊了「獲得道具」關閉視窗")
                        time.sleep(1.0)
                    else:
                        self.context.controller.tap(80, 500)
                        time.sleep(1.0)
                else:
                    self.context.controller.tap(80, 500)
                    time.sleep(1.0)

                bought_count += 1

                print(f"  [多次購買檢查] 檢查 {text} 是否還有剩餘購買次數...")
                fresh_screen = self.context.controller.screenshot()
                fresh_match = self.context.matcher.match_template(
                    fresh_screen,
                    self.asset_path(template_name),
                    threshold=self.ITEM_TEMPLATE_THRESHOLD,
                    roi=(roi_x, roi_y, roi_w, roi_h),
                )
                if fresh_match is None:
                    print(f"    {text} 已完全售罄或變灰。")
                    break
                print(f"    {text} 還有剩餘次數，繼續購買。")

        return bought_count

    def _find_buyable_item_candidates(self, screen) -> list:
        raw_candidates = []
        for text, icon_name, price_name, column_name in self.TARGET_ITEM_TEMPLATES:
            search_roi = self.ITEM_COLUMN_ROIS[column_name]
            icon_matches = self.context.matcher.match_template_all(
                screen,
                self.asset_path(icon_name),
                threshold=self.ITEM_ICON_THRESHOLD,
                roi=search_roi,
                max_results=8,
                min_center_distance=50,
            )
            for icon_match in icon_matches:
                price_roi = self._price_roi_for_icon(screen, icon_match.center)
                price_match = self.context.matcher.match_template(
                    screen,
                    self.asset_path(price_name),
                    threshold=self.ITEM_PRICE_VERIFY_THRESHOLD,
                    roi=price_roi,
                )
                if price_match is None:
                    continue
                raw_candidates.append((text, price_name, price_match))

            fallback_threshold = self.ITEM_PRICE_ONLY_FALLBACKS.get(text)
            if fallback_threshold is not None:
                price_matches = self.context.matcher.match_template_all(
                    screen,
                    self.asset_path(price_name),
                    threshold=fallback_threshold,
                    roi=search_roi,
                    max_results=8,
                    min_center_distance=50,
                )
                for price_match in price_matches:
                    raw_candidates.append((text, price_name, price_match))

        raw_candidates.sort(key=lambda item: item[2].confidence, reverse=True)
        candidates = []
        min_distance_sq = self.ITEM_CLUSTER_DISTANCE * self.ITEM_CLUSTER_DISTANCE
        for candidate in raw_candidates:
            center = candidate[2].center
            if any(
                (center[0] - kept[2].center[0]) ** 2 + (center[1] - kept[2].center[1]) ** 2
                < min_distance_sq
                for kept in candidates
            ):
                continue
            candidates.append(candidate)

        candidates.sort(key=lambda item: (item[2].center[1], item[2].center[0], item[0]))
        return candidates

    def _price_roi_for_icon(self, screen, center):
        cx, cy = center
        dx, dy, width, height = self.ITEM_PRICE_ROI_OFFSET
        roi_x = max(0, cx + dx)
        roi_y = max(0, cy + dy)
        roi_w = min(screen.shape[1], roi_x + width) - roi_x
        roi_h = min(screen.shape[0], roi_y + height) - roi_y
        return roi_x, roi_y, roi_w, roi_h

    @staticmethod
    def _expanded_roi_around_bbox(screen, bbox, exp: int = 40):
        bx, by, bw, bh = bbox
        roi_x = max(0, bx - exp)
        roi_y = max(0, by - exp)
        roi_w = min(screen.shape[1], bx + bw + exp) - roi_x
        roi_h = min(screen.shape[0], by + bh + exp) - roi_y
        return roi_x, roi_y, roi_w, roi_h

    def _save_dry_run_template_debug(self, screen, text: str, match) -> None:
        debug_path = Path(__file__).parent / "debug_output" / f"dry_run_template_{text}_{int(time.time())}.png"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_img = screen.copy()
        bx, by, bw, bh = match.bbox
        cv2.rectangle(debug_img, (bx, by), (bx + bw, by + bh), (0, 0, 255), 2)
        cv2.putText(
            debug_img,
            f"{text} {match.confidence:.2f}",
            (bx, max(18, by - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        cv2.imwrite(str(debug_path), debug_img)
        print(f"    截圖已儲存至：{debug_path.relative_to(Path(__file__).parent)}")

    def execute(self, dry_run: bool = False, ask_refresh: bool = False) -> str:
        if dry_run:
            print("🔍 啟動「辨識測試模式 (Dry Run)」...")
            print("此模式下不會做任何點擊與滑動，僅儲存比對框線截圖並印出信心度。")
            self.buy_items_on_screen(dry_run=True)
            return "Dry run finished."

        total_bought = 0
        max_refreshes = 15
        refreshes = 0

        while refreshes < max_refreshes:
            print(f"\n=========================================")
            print(f"商店第 {refreshes + 1} 頁掃描開始...")
            print(f"=========================================")

            total_bought += self._scan_shop_views()

            # 判斷是否刷新
            print("  ⏳ [辨識中] 正在讀取目前剩餘金幣...")
            screen = self.context.controller.screenshot()
            current_coins = self.get_current_coins(screen)

            can_refresh = False
            refresh_center = None

            if current_coins >= 12000:
                print(f"  💰 目前金幣為 {current_coins}k (>= 12000k 安全線)，繼續檢查右上角刷新按鈕...")

                print("  [辨識中] 正在交叉比對右上角 100/200 紅鑽刷新按鈕...")
                refresh_match = self._find_safe_refresh_100(screen)
                if refresh_match is not None:
                    can_refresh = True
                    refresh_center = refresh_match.center

                if can_refresh:
                    print("  ✅ [判定結果] 系統建議：可以執行刷新！(理由：金幣充足，且右上角標籤為 100 紅鑽)")
                else:
                    print("  ❌ [判定結果] 系統建議：不應該刷新！(理由：金幣雖然充足，但右上角標籤不是 100 紅鑽，可能已經漲價到 200 或達上限)")
            else:
                can_refresh = False
                print(f"  ❌ [判定結果] 系統建議：不應該刷新！(理由：金幣僅剩 {current_coins}k，低於 12000k 安全線，需保留財力)")

            # --------------------------------------------------
            # 最後確認是否要刷新
            # --------------------------------------------------
            default_ans = 'y' if can_refresh else 'n'

            if ask_refresh:
                ans = input(f"\n👉 請問要刷新嗎? (y/n) [預設為 {default_ans}]: ").strip().lower()
                # 如果直接按 Enter，就採用預設值
                if not ans:
                    ans = default_ans
            else:
                ans = default_ans
                if ans == 'y':
                    print("\n🔄 系統判定可刷新，自動進入下一輪...")
                else:
                    print("\n🛑 系統判定不應刷新，自動結束任務。")

            if ans == 'y':
                if not can_refresh:
                    print("⚠️ 警告：系統原本不建議刷新，但您選擇了強制刷新！")

                print("🔄 正在點擊刷新按鈕...")
                if refresh_center:
                    self.context.controller.tap(*refresh_center)
                else:
                    # 如果 OCR 沒抓到中心點，使用預設座標 (大約在右上角)
                    self.context.controller.tap(850, 55)

                time.sleep(1.0)

                # 自動尋找並點擊「是」按鈕
                print("  ⏳ [檢查中] 正在尋找刷新二次確認的「是」按鈕...")
                confirm_path = self.asset_path("是.png")
                clicked_confirm = False
                if confirm_path.exists():
                    confirm_screen = self.context.controller.screenshot()
                    confirm_match = self.context.matcher.match_template(confirm_screen, confirm_path, threshold=0.82)
                    if confirm_match is not None:
                        self.context.controller.tap(*confirm_match.center)
                        print("    ✅ 成功點擊了「是」按鈕！")
                        clicked_confirm = True
                        time.sleep(1.5)

                if not clicked_confirm:
                    print("    ⚠️ 畫面上沒有看到「是」按鈕，可能不需要確認。")

                refreshes += 1
            else:
                print("🛑 停止刷新，結束商店掃蕩任務。")
                break

        print(f"\n🎉 魔法商店自動購買結束！")
        self._return_to_daily_tasks()
        return f"Bought {total_bought} items, refreshed {refreshes} times."

    def _find_safe_refresh_100(self, screen):
        match_100 = self._refresh_template_probe(screen, "刷新100.png")
        match_200 = self._refresh_template_probe(screen, "刷新200.png")
        conf_100 = match_100.confidence
        conf_200 = match_200.confidence
        print(f"    refresh_100_conf={conf_100:.3f}, refresh_200_conf={conf_200:.3f}")

        if conf_100 < self.REFRESH_TEMPLATE_THRESHOLD:
            return None
        if conf_200 >= self.REFRESH_TEMPLATE_THRESHOLD and conf_100 - conf_200 < self.REFRESH_TEMPLATE_MARGIN:
            return None
        return match_100

    def _refresh_template_probe(self, screen, asset_name: str):
        x, y, w, h = self.REFRESH_BUTTON_ROI
        haystack = screen[y:y + h, x:x + w]
        if haystack.ndim == 3 and haystack.shape[2] == 4:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_BGRA2BGR)

        template = read_image(self.asset_path(asset_name), cv2.IMREAD_COLOR)
        crop_x = min(self.REFRESH_TEMPLATE_DIGIT_CROP_X, max(0, template.shape[1] - 1))
        template = template[:, crop_x:]
        th, tw = template.shape[:2]
        if th > haystack.shape[0] or tw > haystack.shape[1]:
            return SimpleNamespace(confidence=0.0, center=(x + w // 2, y + h // 2))

        result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        return SimpleNamespace(
            confidence=float(max_val),
            center=(x + max_loc[0] + tw // 2, y + max_loc[1] + th // 2),
        )

    def _scan_shop_views(self) -> int:
        """Scan stable top/middle/bottom shop views with overlap."""
        bought_count = 0
        for view_index in range(self.SHOP_SCAN_VIEWS):
            print(f"  [商品區段] 掃描第 {view_index + 1}/{self.SHOP_SCAN_VIEWS} 個位置...")
            bought_count += self.buy_items_on_screen()
            if view_index + 1 >= self.SHOP_SCAN_VIEWS:
                continue

            x1, y1, x2, y2, duration = self.SHOP_SWIPE
            print("  [滑動] 向下捲動一個重疊區段...")
            self.context.controller.swipe(x1, y1, x2, y2, duration_ms=duration)
            time.sleep(self.SHOP_SETTLE_SECONDS)
        return bought_count

    def _return_to_daily_tasks(self) -> None:
        if self.context.navigator.go_to_daily_tasks(max_steps=1):
            return

        for _ in range(2):
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(
                screen,
                self.asset_path("back_arrow.png"),
                threshold=0.82,
                roi=self.BACK_ARROW_ROI,
            )
            if match is None:
                break

            self.context.controller.tap(*match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)
            if self.context.navigator.go_to_daily_tasks(max_steps=2):
                return

        raise TaskFailedError("Magic Shop completed, but could not return to Daily Tasks safely")
