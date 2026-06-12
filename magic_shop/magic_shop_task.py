from __future__ import annotations

import time
import sys
import cv2
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SHARED_ASSETS_DIR, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.task_runner import BaseTask
from src.exceptions import TaskFailedError
from src.ocr_utils import build_easyocr_reader, read_texts_easyocr, parse_power_value

class MagicShopTask(BaseTask):
    spec = TASK_SPECS["magic_shop"]
    required_assets = (
        "紫珠960k.png",
        "競技場券480k.png",
        "金牌5000k.png",
        "英雄碎片1800k.png",
        "碎片買滿.png",
        "購買.png",
        "獲得道具.png",
        "是.png",
        "back_arrow.png",
    )
    BACK_ARROW_ROI = (0, 0, 100, 80)
    SHOP_ITEM_ROI = (250, 100, 710, 440)

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

    # 改用 OCR 辨識字串，取代原本的圖片比對
    # 由於字體太擠，5000k 有時會被吃掉一個零變成 500k，甚至吃掉 k 變成 5000，因此我們把容錯清單加大
    TARGET_PRICES = ["960k", "960", "480k", "480", "5000k", "5000", "1800k", "1800", "500k", "500"]

    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None

    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            print("  ⏳ 正在初始化 OCR 引擎載入模型 (初次啟動需要幾秒鐘，請稍候)...")
            self._ocr_reader = build_easyocr_reader()
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
        if ignore_boxes is None:
            ignore_boxes = []

        bought_count = 0
        loop_limit = 1
        loop_count = 0

        # 商店商品區塊在畫面右側（X軸 250 以後），避開左側的「魔法商店」等中文選單
        # Y軸 100~540 避開頂端金幣與底部邊界。 w=710 代表掃描到 960 (250+710)
        ocr_roi = (250, 100, 710, 440)

        while loop_count < loop_limit:
            loop_count += 1
            screen = self.context.controller.screenshot()
            found_any = False

            # 截取 ROI
            x, y, w, h = ocr_roi
            roi_img = screen[y:y+h, x:x+w]

            print("  ⏳ [辨識中] 正在呼叫 OCR 掃描畫面上的商品價格 (這可能需要 1~2 秒)...")
            # 使用 allowlist 強制模型只輸出數字、k、m 和逗號
            # 經過測試，mag_ratio=3.0 能讓 5000k 的信心度從 0.69 暴增到 0.97！
            ocr_results = self._get_ocr_reader().readtext(roi_img, detail=1, allowlist="0123456789km,", mag_ratio=3.0)
            print(f"  ✅ [掃描完成] 共發現 {len(ocr_results)} 個潛在文字區塊。")

            fragments = []
            for box, text, confidence in ocr_results:
                offset_box = [[pt[0] + x, pt[1] + y] for pt in box]
                fragments.append({
                    "text": str(text),
                    "confidence": float(confidence),
                    "box": offset_box
                })

            print("  [OCR 偵測結果] 本次掃描到的文字 (信心度 >= 0.30)：")
            for frag in fragments:
                if frag['confidence'] >= 0.30:
                    print(f"    - '{frag['text']}' (信心度: {frag['confidence']:.3f})")

            for frag in fragments:
                text = str(frag['text']).lower().replace(' ', '').replace(',', '')
                confidence = frag['confidence']

                # 因為我們有了「圖片比對」這個終極雙重確認機制，就算錯認也沒關係
                # OCR 就算非常不確定 (信心度 > 0.35)，我們也可以大膽放行給後方的圖片比對去嚴格把關
                if text in self.TARGET_PRICES and confidence > 0.35:
                    box = frag['box']
                    center_x = int((box[0][0] + box[2][0]) / 2)
                    center_y = int((box[0][1] + box[2][1]) / 2)

                    # 檢查是否為已售罄(忽略)的座標
                    is_ignored = False
                    for ibox in ignore_boxes:
                        if ibox[0][0] - 20 <= center_x <= ibox[2][0] + 20 and ibox[0][1] - 20 <= center_y <= ibox[2][1] + 20:
                            is_ignored = True
                            break
                    if is_ignored:
                        continue

                    # 準備對應的模板圖檔名稱
                    template_map = {
                        "960k": "紫珠960k.png",
                        "960": "紫珠960k.png",
                        "480k": "競技場券480k.png",
                        "480": "競技場券480k.png",
                        "5000k": "金牌5000k.png",
                        "5000": "金牌5000k.png",
                        "500k": "金牌5000k.png",  # 容錯
                        "500": "金牌5000k.png",
                        "1800k": "英雄碎片1800k.png",
                        "1800": "英雄碎片1800k.png"
                    }
                    template_name = template_map.get(text)

                    if template_name:
                        print(f"  🔍 [驗證中] OCR 鎖定 {text}，正在拿原圖 ({template_name}) 進行亮度與形狀雙重驗證...")
                        # 【方案二】雙重確認：用圖片比對來驗證該區域是否為「亮著的」按鈕
                        # 設定一個涵蓋此 OCR 框框的 ROI (向外擴張 40 像素)
                        exp = 40
                        roi_x = max(0, int(box[0][0]) - exp)
                        roi_y = max(0, int(box[0][1]) - exp)
                        roi_w = min(screen.shape[1], int(box[2][0]) + exp) - roi_x
                        roi_h = min(screen.shape[0], int(box[2][1]) + exp) - roi_y

                        match = self.context.matcher.match_template(
                            screen, self.asset_path(template_name), threshold=0.60, roi=(roi_x, roi_y, roi_w, roi_h)
                        )

                        # vision_matcher 內建了 brightness < 75% 的阻擋機制，如果回傳 None 代表按鈕暗掉了 (售罄)
                        if match is None:
                            print(f"    ⚠️ [雙重確認] OCR 找到 {text}，但圖片比對失敗 (按鈕可能變灰售罄)，自動跳過。")
                            ignore_boxes.append(box)
                            continue
                    else:
                        # 如果沒有對應的圖片 (防呆)，就直接當作成功
                        pass

                    print(f"  ➡️ [OCR+比對] 成功鎖定目標：{text}，信心度：{confidence:.3f}")

                    if dry_run:
                        debug_path = Path(__file__).parent / "debug_output" / f"dry_run_ocr_{text}_{int(time.time())}.png"
                        debug_path.parent.mkdir(parents=True, exist_ok=True)
                        debug_img = screen.copy()
                        cv2.rectangle(debug_img, (int(box[0][0]), int(box[0][1])), (int(box[2][0]), int(box[2][1])), (0,0,255), 2)
                        cv2.putText(debug_img, f"{text} {confidence:.2f}", (int(box[0][0]), int(box[0][1])-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                        cv2.imwrite(str(debug_path), debug_img)
                        print(f"    📸 截圖已儲存至：{debug_path.relative_to(Path(__file__).parent)}")
                        found_any = True
                        continue

                    # ----------------------------------
                    # 進入購買迴圈 (處理有數量的商品，例如買 3 次碎片)
                    # ----------------------------------
                    while True:
                        self.context.controller.tap(center_x, center_y)
                        time.sleep(1.0)

                        # 點擊商品後，有些商品可能會跳出數量選擇
                        max_btn_path = self.asset_path("碎片買滿.png")
                        if max_btn_path.exists():
                            max_match = self.context.matcher.match_template(self.context.controller.screenshot(), max_btn_path, threshold=0.82)
                            if max_match is not None:
                                self.context.controller.tap(*max_match.center)
                                print(f"    🌟 點擊了「碎片買滿」")
                                time.sleep(0.5)

                        # 尋找購買按鈕
                        print("  ⏳ [等待中] 正在尋找「購買確認」按鈕...")
                        buy_btn_path = self.asset_path("購買.png")
                        buy_match = None
                        if buy_btn_path.exists():
                            buy_screen = self.context.controller.screenshot()
                            buy_match = self.context.matcher.match_template(buy_screen, buy_btn_path, threshold=0.82)

                        if buy_match is not None:
                            self.context.controller.tap(*buy_match.center)
                            print(f"    ✅ 點擊了購買按鈕！")
                            time.sleep(1.5)

                            print("  ⏳ [檢查中] 檢查是否有獲得道具的關閉視窗...")
                            reward_path = self.asset_path("獲得道具.png")
                            if reward_path.exists():
                                reward_match = self.context.matcher.match_template(self.context.controller.screenshot(), reward_path, threshold=0.82)
                                if reward_match is not None:
                                    self.context.controller.tap(*reward_match.center)
                                    print(f"    🎁 點擊了「獲得道具」關閉視窗")
                                    time.sleep(1.0)
                                else:
                                    self.context.controller.tap(80, 500)
                                    time.sleep(1.0)
                            else:
                                self.context.controller.tap(80, 500)
                                time.sleep(1.0)

                            bought_count += 1
                            found_any = True

                            # 買完一次後，原地再次截圖比對，確認按鈕是否變灰
                            if template_name:
                                print(f"  🔍 [多次購買檢查] 檢查 {text} 是否還有剩餘購買次數...")
                                fresh_screen = self.context.controller.screenshot()
                                fresh_match = self.context.matcher.match_template(
                                    fresh_screen, self.asset_path(template_name), threshold=0.60, roi=(roi_x, roi_y, roi_w, roi_h)
                                )
                                if fresh_match is None:
                                    print(f"    ✅ {text} 已完全售罄 (按鈕變灰)！")
                                    break
                                else:
                                    print(f"    🔄 {text} 還有剩餘次數，繼續購買！")
                            else:
                                break

                        else:
                            print(f"    ⚠️ 點擊了 {text} 但沒有出現購買按鈕，可能已售罄。將其加入忽略清單。")
                            ignore_boxes.append(box)
                            found_any = True
                            break # 結束迴圈

                    # 該商品徹底買完或失敗後，跳到下一個 OCR 區塊
                    continue

            if dry_run:
                break

        return bought_count

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

            # 總共約 6 排商品，一頁顯示 2~3 排
            # 應使用者要求：極限加大滑動幅度為 420 像素 (從 520 滑到 100)，並且只要檢查 2 個畫面就好！
            for swipe_idx in range(2):
                bought = self.buy_items_on_screen()
                total_bought += bought

                if swipe_idx < 1: # 最後一次檢查完不用再滑
                    print("  👇 [滑動] 向下極限捲動查看更多商品...")
                    # 從 520 滑到 0 (極限滑動 520 像素)
                    self.context.controller.swipe(480, 520, 480, 0, duration_ms=500)
                    time.sleep(1.0)

            # 判斷是否刷新
            print("  ⏳ [辨識中] 正在讀取目前剩餘金幣...")
            screen = self.context.controller.screenshot()
            current_coins = self.get_current_coins(screen)

            can_refresh = False
            refresh_center = None

            if current_coins >= 12000:
                print(f"  💰 目前金幣為 {current_coins}k (>= 12000k 安全線)，繼續檢查右上角刷新按鈕...")

                print("  ⏳ [辨識中] 正在掃描右上角刷新按鈕 (OCR)...")
                # 檢查 100 紅鑽按鈕 (使用 OCR 避免 100 跟 200 誤判)
                # 根據截圖，按鈕大約在畫面右上角，x=750~950, y=20~90
                refresh_roi = (750, 20, 200, 70)
                rx, ry, rw, rh = refresh_roi
                refresh_img = screen[ry:ry+rh, rx:rx+rw]

                # 使用 OCR 辨識字串，嚴格白名單只允許數字
                refresh_res = self._get_ocr_reader().readtext(refresh_img, detail=1, allowlist="0123456789", mag_ratio=3.0)

                for box, text, conf in refresh_res:
                    if str(text) == "100" and conf > 0.60:
                        can_refresh = True
                        refresh_center = (int(rx + (box[0][0] + box[2][0]) / 2), int(ry + (box[0][1] + box[2][1]) / 2))
                        break

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
