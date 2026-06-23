import logging
import time
from pathlib import Path

import cv2
import numpy as np
from src.adb_controller import DeviceController
from src.ocr_utils import get_cached_easyocr_reader, read_texts_easyocr
from src.vision_matcher import VisionMatcher, read_image

logger = logging.getLogger(__name__)

class ArcaneForgeAscendTask:
    """
    奧術熔爐 (Arcane Forge) 升星任務
    """
    def __init__(self, ctrl: DeviceController, vm: VisionMatcher, target_max_stats: int = 2):
        self.ctrl = ctrl
        self.vm = vm
        self.target_max_stats = target_max_stats

        # 預設 Template 路徑
        self.asset_dir = Path("arcane_forge/assets/manual")
        self.ascend_btn_tpl = self.asset_dir / "升星.png"
        self.auto_add_btn_tpl = self.asset_dir / "自動添加.png"
        self.ascend_success_tpl = self.asset_dir / "升星成功.png"
        self.max_stat_tpl = self.asset_dir / "最大.png"
        self.lock_btn_tpl = self.asset_dir / "鎖定.png"
        self.back_btn_tpl = self.asset_dir / "返回.png"
        # 預先載入 OCR
        self.reader = get_cached_easyocr_reader(("en",))

        # 第一格符文的精準固定座標
        self.first_slot_pos = (572, 148)
        # 第一格符文的邊界範圍 (供 Debug 畫框用)
        self.first_slot_box = (516, 94, 112, 109)

    def run(self):
        logger.debug("開始執行奧術熔爐升星 (Arcane Forge Ascend) 任務...")

        loop_count = 1
        while True:
            logger.debug(f"--- 升星循環第 {loop_count} 次 ---")

            # 步驟 A：選取符文與進入彈窗
            logger.debug("點擊第一格符文")
            if hasattr(self, 'first_slot_box'):
                x, y, w, h = self.first_slot_box
                self.ctrl.annotate_next_tap_debug(boxes=[(x, y, w, h, "First Slot Box")])
            self.ctrl.tap(*self.first_slot_pos)
            time.sleep(1.0)

            screen = self.ctrl.screenshot()
            ascend_res = self.vm.match_template(screen, self.ascend_btn_tpl)
            if not ascend_res:
                logger.info("未找到「升星」按鈕，可能無符文可升星，結束任務")
                return True

            logger.debug("點擊「升星」進入彈窗")
            self.ctrl.tap(ascend_res.x, ascend_res.y)
            time.sleep(1.0)

            # 步驟 B：OCR 判斷紫粉數量 (重要防呆)
            screen = self.ctrl.screenshot()
            # 精準鎖定彈窗內紫粉數量 (x, y, w, h)
            roi = (500, 110, 100, 40)
            ocr_results = read_texts_easyocr(screen, roi=roi, reader=self.reader, allowlist="0123456789,")

            dust_amount = -1
            confidence = 0.0
            if ocr_results:
                # 取得信心度最高的數字
                best_match = max(ocr_results, key=lambda x: x['confidence'])
                # 過濾逗號再轉型
                clean_text = best_match['text'].replace(',', '')
                confidence = best_match['confidence']
                try:
                    dust_amount = int(clean_text)
                except ValueError:
                    pass

            if dust_amount != -1 and dust_amount < 180:
                logger.warning(f"OCR 解析紫粉數量不足 ({dust_amount} < 180)，結束任務以保護資源")
                return True
            elif dust_amount == -1:
                logger.warning("紫粉數量解析失敗，假設仍有足夠材料，繼續執行...")
            else:
                logger.debug(f"當前紫粉數量: {dust_amount} (信心值: {confidence:.2f})，繼續升星...")

            # 步驟 C：執行升星與等待
            screen = self.ctrl.screenshot()
            auto_add_res = self.vm.match_template(screen, self.auto_add_btn_tpl)
            if auto_add_res:
                logger.debug("點擊「自動添加」")
                self.ctrl.tap(auto_add_res.x, auto_add_res.y)
                time.sleep(0.5)
            else:
                logger.warning("未找到「自動添加」")

            screen = self.ctrl.screenshot()
            ascend_confirm_res = self.vm.match_template(screen, self.ascend_btn_tpl)
            if ascend_confirm_res:
                logger.debug("點擊彈窗內「升星」")
                self.ctrl.tap(ascend_confirm_res.x, ascend_confirm_res.y)
            else:
                logger.warning("未找到彈窗內「升星」")

            # Polling 60 秒等待升星成功
            success = False
            logger.debug("等待升星成功畫面...")
            for _ in range(30):
                screen = self.ctrl.screenshot()
                success_res = self.vm.match_template(screen, self.ascend_success_tpl)
                if success_res:
                    success = True
                    break
                time.sleep(2.0)

            if not success:
                logger.warning("等待 60 秒未見「升星成功」，可能卡頓嚴重或資源耗盡，結束任務")
                return True

            logger.debug("升星成功！")

            # 步驟 D：極品判斷與上鎖
            screen = self.ctrl.screenshot()
            max_count = 0
            if self.max_stat_tpl.exists():
                template_raw = read_image(self.max_stat_tpl, cv2.IMREAD_UNCHANGED)
                # 處理 alpha 通道或直接轉 BGR
                if template_raw.ndim == 3 and template_raw.shape[2] == 4:
                    template = template_raw[:, :, :3]
                    alpha = template_raw[:, :, 3]
                    mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)[1]
                    if np.all(mask == 255):
                        mask = None
                else:
                    template = template_raw
                    mask = None

                if mask is not None:
                    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED, mask=mask)
                else:
                    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)

                locs = np.where(result >= 0.8)
                points = list(zip(locs[1], locs[0]))

                # 簡易 NMS (Non-Maximum Suppression) 去除鄰近重複點
                filtered_points = []
                for pt in points:
                    if not any((pt[0] - fp[0])**2 + (pt[1] - fp[1])**2 < 100 for fp in filtered_points):
                        filtered_points.append(pt)

                max_count = len(filtered_points)

            logger.info(f"第 {loop_count} 顆符文升星完畢，獲得 {max_count} 個「最大」屬性")

            # 點擊安全空白處關閉特效
            logger.debug("點擊空白處關閉特效")
            self.ctrl.tap(480, 50)
            time.sleep(1.0)

            if max_count >= self.target_max_stats:
                logger.info("✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨")
                logger.info(f"✨ 恭喜！發現 {max_count} 頂屬性極品符文！準備上鎖... ✨")
                logger.info("✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨")
                screen = self.ctrl.screenshot()
                lock_res = self.vm.match_template(screen, self.lock_btn_tpl)
                if lock_res:
                    self.ctrl.tap(lock_res.x, lock_res.y)
                    time.sleep(0.5)
                else:
                    logger.warning("未找到「鎖定」按鈕")

            # 退回列表
            logger.debug("點擊「返回」")
            screen = self.ctrl.screenshot()
            back_res = self.vm.match_template(screen, self.back_btn_tpl)
            if back_res:
                self.ctrl.tap(back_res.x, back_res.y)
            else:
                logger.warning("未找到「返回」按鈕，使用系統返回")
                self.ctrl.back()
            time.sleep(1.0)
            loop_count += 1

        return True
