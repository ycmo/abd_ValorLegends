"""
vision_matcher.py
-----------------
VisionMatcher: 多模板比對 + ROI 裁剪 + 信心值回傳 + Debug 畫框輸出。

設計原則：
  - match_templates()：從一個資料夾載入全部 template，在指定 ROI 中分別比對，
    回傳所有結果中 confidence 最高者。
  - save_debug_image()：在截圖上用方框標記匹配位置與信心值，輸出到 debug 目錄。
  - 所有座標均為原始全圖座標，方便直接傳給 ADB tap。
"""

import os
import glob
import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class MatchResult:
    """一次 template 比對的結果。"""
    template_path: str          # 使用的 template 檔案路徑
    confidence: float           # TM_CCOEFF_NORMED 分數 (0.0 ~ 1.0)
    center: Tuple[int, int]     # 匹配中心點（全圖座標）
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)（全圖座標）
    roi_name: str               # 此次搜尋的 ROI 名稱

    def __str__(self) -> str:
        return (
            f"[{self.roi_name}] template={os.path.basename(self.template_path)} "
            f"conf={self.confidence:.4f} "
            f"center={self.center} bbox={self.bbox}"
        )


# 預設四角 ROI 定義（y_start, y_end, x_start, x_end）
# 這些比例區域涵蓋廣告關閉按鈕最常出現的位置。
# 若截圖解析度為 1600x900，會在 VisionMatcher.__init__ 中動態計算。
DEFAULT_ROI_RATIOS = {
    "top_right":    (0.00, 0.20, 0.70, 1.00),  # 右上角 20% × 30%
    "top_left":     (0.00, 0.20, 0.00, 0.30),  # 左上角 20% × 30%
    "bottom_right": (0.80, 1.00, 0.70, 1.00),  # 右下角 20% × 30%
    "bottom_left":  (0.80, 1.00, 0.00, 0.30),  # 左下角 20% × 30%
}


class VisionMatcher:
    def __init__(
        self,
        screen_width: int = 1600,
        screen_height: int = 900,
        threshold: float = 0.80,
        debug: bool = False,
        debug_dir: str = "screenshots/debug",
    ):
        """
        Parameters
        ----------
        screen_width, screen_height : int
            模擬器解析度，用於將 ROI 比例轉換為像素座標。
        threshold : float
            比對通過的最低信心值，0.80 ~ 0.85 是廣告關閉按鈕的常見設定值。
        debug : bool
            開啟時，每次 match 會在 debug_dir 儲存標記框圖片。
        debug_dir : str
            Debug 截圖的輸出目錄。
        """
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.threshold = threshold
        self.debug = debug
        self.debug_dir = debug_dir
        if debug:
            os.makedirs(debug_dir, exist_ok=True)

        # 根據畫面解析度計算 ROI 像素座標
        self.rois = self._build_rois(screen_width, screen_height)

    # ------------------------------------------------------------------
    # 主要 API
    # ------------------------------------------------------------------

    def match_templates(
        self,
        screen: np.ndarray,
        template_dir: str,
        rois: Optional[dict] = None,
        debug_tag: str = "match",
    ) -> Optional[MatchResult]:
        """
        從 template_dir 載入全部 PNG template，
        在每個 ROI 中逐一比對，回傳 confidence 最高的結果（若 >= threshold），
        否則回傳 None。

        Parameters
        ----------
        screen : np.ndarray
            由 DeviceController.screenshot() 回傳的 BGR 全圖。
        template_dir : str
            存放 template PNG 的資料夾。
        rois : dict, optional
            自訂 ROI 字典 {"name": (y1, y2, x1, x2)}。
            若為 None 則使用四角預設 ROI。
        debug_tag : str
            Debug 圖片的檔名前綴（避免覆蓋）。

        Returns
        -------
        MatchResult or None
        """
        templates = self._load_templates(template_dir)
        if not templates:
            print(f"[VisionMatcher] WARNING: No PNG templates found in {template_dir!r}")
            return None

        active_rois = rois if rois is not None else self.rois
        best: Optional[MatchResult] = None

        for roi_name, (y1, y2, x1, x2) in active_rois.items():
            # 確保 ROI 在圖像範圍內
            y1c = max(0, y1)
            y2c = min(screen.shape[0], y2)
            x1c = max(0, x1)
            x2c = min(screen.shape[1], x2)

            roi_img = screen[y1c:y2c, x1c:x2c]
            if roi_img.size == 0:
                continue

            for tmpl_path, tmpl in templates.items():
                th, tw = tmpl.shape[:2]
                rh, rw = roi_img.shape[:2]

                if th > rh or tw > rw:
                    # Template 比 ROI 大，跳過
                    continue

                result_map = cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result_map)

                confidence = float(max_val)
                # 計算全圖座標
                abs_x = max_loc[0] + x1c
                abs_y = max_loc[1] + y1c
                center_x = abs_x + tw // 2
                center_y = abs_y + th // 2

                mr = MatchResult(
                    template_path=tmpl_path,
                    confidence=confidence,
                    center=(center_x, center_y),
                    bbox=(abs_x, abs_y, tw, th),
                    roi_name=roi_name,
                )

                if best is None or confidence > best.confidence:
                    best = mr

        # 輸出每次掃描的最佳結果（無論是否通過 threshold）
        if best is not None:
            status = "HIT" if best.confidence >= self.threshold else "miss"
            print(f"[VisionMatcher] {status}: {best}")

        # Debug 畫框
        if self.debug and best is not None and best.confidence >= self.threshold:
            self.save_debug_image(screen, best, debug_tag)

        if best is not None and best.confidence >= self.threshold:
            return best

        return None

    def check_anchor(
        self,
        screen: np.ndarray,
        anchor_path: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """
        在全圖中比對一張 anchor template，回傳 (是否通過, confidence)。
        通常用來確認是否已回到遊戲大廳。

        Parameters
        ----------
        anchor_path : str
            Anchor template 圖片路徑。
        threshold : float, optional
            若不指定，使用 self.threshold。
        """
        thr = threshold if threshold is not None else self.threshold
        if not os.path.exists(anchor_path):
            print(f"[VisionMatcher] Anchor not found: {anchor_path!r}")
            return False, 0.0

        tmpl = cv2.imread(anchor_path, cv2.IMREAD_COLOR)
        if tmpl is None:
            print(f"[VisionMatcher] Cannot read anchor: {anchor_path!r}")
            return False, 0.0

        th, tw = tmpl.shape[:2]
        sh, sw = screen.shape[:2]
        if th > sh or tw > sw:
            print(f"[VisionMatcher] Anchor template larger than screen, skipping.")
            return False, 0.0

        result_map = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result_map)
        confidence = float(max_val)
        passed = confidence >= thr
        print(
            f"[VisionMatcher] anchor={os.path.basename(anchor_path)} "
            f"conf={confidence:.4f} {'PASS' if passed else 'fail'}"
        )
        return passed, confidence

    # ------------------------------------------------------------------
    # Debug 輸出
    # ------------------------------------------------------------------

    def save_debug_image(
        self,
        screen: np.ndarray,
        result: MatchResult,
        tag: str = "debug",
        save_path: Optional[str] = None,
    ) -> str:
        """
        在截圖上畫出 bbox 方框與信心值文字，儲存並回傳路徑。
        """
        import time
        debug_img = screen.copy()
        x, y, w, h = result.bbox
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 0, 255), 2)  # 紅框
        cv2.circle(debug_img, result.center, 6, (0, 255, 0), -1)           # 綠點
        label = f"{os.path.basename(result.template_path)} {result.confidence:.3f}"
        cv2.putText(
            debug_img, label,
            (x, max(y - 8, 15)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
        )

        if save_path is None:
            ts = time.strftime("%H%M%S")
            save_path = os.path.join(self.debug_dir, f"{tag}_{ts}.png")

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        cv2.imwrite(save_path, debug_img)
        print(f"[VisionMatcher] Debug image saved: {save_path}")
        return save_path

    def save_failed_screenshot(self, screen: np.ndarray, tag: str = "failed") -> str:
        """
        儲存 FAILED 狀態下的裸截圖（不加框），用於事後分析。
        """
        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.debug_dir, f"{tag}_{ts}.png")
        os.makedirs(self.debug_dir, exist_ok=True)
        cv2.imwrite(path, screen)
        print(f"[VisionMatcher] Failed screenshot saved: {path}")
        return path

    # ------------------------------------------------------------------
    # 內部工具
    # ------------------------------------------------------------------

    def _build_rois(self, w: int, h: int) -> dict:
        """將比例 ROI 定義轉換為像素 ROI 座標 {name: (y1, y2, x1, x2)}。"""
        rois = {}
        for name, (ry1, ry2, rx1, rx2) in DEFAULT_ROI_RATIOS.items():
            rois[name] = (
                int(ry1 * h), int(ry2 * h),
                int(rx1 * w), int(rx2 * w),
            )
        return rois

    @staticmethod
    def _load_templates(template_dir: str) -> dict:
        """從資料夾載入全部 PNG 檔，回傳 {path: ndarray}。"""
        templates = {}
        pattern = os.path.join(template_dir, "*.png")
        for path in sorted(glob.glob(pattern)):
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is not None:
                templates[path] = img
            else:
                print(f"[VisionMatcher] WARNING: Cannot read template {path!r}")
        return templates
