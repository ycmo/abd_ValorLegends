from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.config import ROOT_DIR, SHARED_ASSETS_DIR


GIFT_PACK_LABEL_TEMPLATE = (
    ROOT_DIR
    / "AwayFromKeyboard"
    / "integration_task"
    / "templates"
    / "blockers"
    / "gift_pack_label.png"
)
GIFT_PACK_LABEL_ROI = (340, 150, 320, 130)
GIFT_PACK_LABEL_THRESHOLD = 0.82
GIFT_PACK_CLOSE_POINT = (660, 22)
REWARD_ACQUIRED_TITLE_TEMPLATE = SHARED_ASSETS_DIR / "reward_acquired_title.png"
REWARD_ACQUIRED_TITLE_ROI = (330, 110, 330, 100)
REWARD_ACQUIRED_TITLE_THRESHOLD = 0.74
REWARD_ACQUIRED_CYAN_ROI = (330, 120, 330, 100)
REWARD_ACQUIRED_CYAN_THRESHOLD = 0.30
REWARD_ACQUIRED_MAX_TAPS = 3
BLOCKER_TEMPLATE_SPECS = (
    ("gift_pack_label.png", GIFT_PACK_LABEL_ROI, GIFT_PACK_LABEL_THRESHOLD),
    ("equipment_pack_label.png", (520, 0, 380, 150), 0.82),
)
POPUP_CLOSE_TEMPLATE_SPECS = (
    ("island_signin_close_x.png", (840, 0, 120, 110), 0.82),
)


class BlockerHandler:
    """Closes known temporary popups that block screen recognition."""

    def __init__(self, controller, *, template_path: Optional[Path] = None):
        self.controller = controller
        self.template_path = template_path or GIFT_PACK_LABEL_TEMPLATE
        self.template_dir = self.template_path.parent

    def handle_known_blocker(self, screen: np.ndarray | None = None) -> bool:
        if screen is None:
            screen = self._screenshot()
        reward_match = self.match_reward_acquired(screen)
        if reward_match is not None:
            return self._dismiss_reward_acquired(reward_match)

        close_match = self.match_popup_close(screen)
        if close_match is not None:
            template_name, confidence, center = close_match
            print(
                f"[Blocker] close popup "
                f"({template_name} confidence={confidence:.2f}, center={center}); tapping close."
            )
            self.controller.tap(*center)
            time.sleep(1.0)
            return True

        match = self.match_gift_pack(screen)
        if match is None:
            return False

        template_name, confidence, center = match
        print(
            f"[Blocker] 偵測到臨時禮包廣告 "
            f"({template_name} confidence={confidence:.2f}, center={center})，點擊跳過..."
        )
        self.controller.tap(*GIFT_PACK_CLOSE_POINT)
        time.sleep(2.0)
        return True

    def match_gift_pack(self, screen: np.ndarray | None) -> Optional[tuple[str, float, tuple[int, int]]]:
        if screen is None:
            return None

        for template_name, roi, threshold in self._template_specs():
            match = self._match_template(screen, template_name, roi, threshold)
            if match is not None:
                return match
        return None

    def match_popup_close(self, screen: np.ndarray | None) -> Optional[tuple[str, float, tuple[int, int]]]:
        if screen is None:
            return None

        for template_name, roi, threshold in self._popup_close_specs():
            match = self._match_template(screen, template_name, roi, threshold)
            if match is not None:
                return match
        return None

    def match_reward_acquired(self, screen: np.ndarray | None) -> Optional[tuple[str, float, tuple[int, int]]]:
        if screen is None:
            return None
        match = self._match_template(
            screen,
            REWARD_ACQUIRED_TITLE_TEMPLATE,
            REWARD_ACQUIRED_TITLE_ROI,
            REWARD_ACQUIRED_TITLE_THRESHOLD,
        )
        if match is not None:
            return match
        return self._match_reward_acquired_by_color(screen)

    def _match_reward_acquired_by_color(self, screen: np.ndarray) -> Optional[tuple[str, float, tuple[int, int]]]:
        x, y, w, h = REWARD_ACQUIRED_CYAN_ROI
        sh, sw = screen.shape[:2]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(sw, x + w)
        y2 = min(sh, y + h)
        if x2 <= x1 or y2 <= y1:
            return None

        crop = screen[y1:y2, x1:x2]
        blue, green, red = cv2.split(crop)
        cyan_mask = (blue > 150) & (green > 110) & (red < 130)
        ratio = float(np.count_nonzero(cyan_mask)) / float(cyan_mask.size)
        if ratio < REWARD_ACQUIRED_CYAN_THRESHOLD:
            return None
        return "reward_acquired_cyan", ratio, (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)

    def _dismiss_reward_acquired(self, match: tuple[str, float, tuple[int, int]]) -> bool:
        current_match = match
        for attempt in range(1, REWARD_ACQUIRED_MAX_TAPS + 1):
            template_name, confidence, center = current_match
            print(
                f"[Blocker] reward acquired overlay "
                f"({template_name} confidence={confidence:.2f}, center={center}); "
                f"tapping overlay {attempt}/{REWARD_ACQUIRED_MAX_TAPS}."
            )
            self.controller.tap(*center)
            time.sleep(1.0)

            screen = self._screenshot()
            if screen is None:
                return True
            next_match = self.match_reward_acquired(screen)
            if next_match is None:
                return True
            current_match = next_match

        template_name, confidence, center = current_match
        print(
            f"[Blocker] reward acquired overlay still visible after "
            f"{REWARD_ACQUIRED_MAX_TAPS} taps "
            f"({template_name} confidence={confidence:.2f}, center={center}); "
            "leaving it for normal route handling."
        )
        return False

    def _template_specs(self):
        specs = []
        for template_name, roi, threshold in BLOCKER_TEMPLATE_SPECS:
            template_path = self.template_dir / template_name
            specs.append((template_path, roi, threshold))
        return specs

    def _popup_close_specs(self):
        specs = []
        for template_name, roi, threshold in POPUP_CLOSE_TEMPLATE_SPECS:
            template_path = self.template_dir / template_name
            specs.append((template_path, roi, threshold))
        return specs

    def _match_template(
        self,
        screen: np.ndarray,
        template_path: Path,
        roi_spec: tuple[int, int, int, int],
        threshold: float,
    ) -> Optional[tuple[str, float, tuple[int, int]]]:
        if not template_path.exists():
            return None

        template = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            return None

        x, y, w, h = roi_spec
        sh, sw = screen.shape[:2]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(sw, x + w)
        y2 = min(sh, y + h)
        if x2 <= x1 or y2 <= y1:
            return None

        roi = screen[y1:y2, x1:x2]
        th, tw = template.shape[:2]
        if th > roi.shape[0] or tw > roi.shape[1]:
            return None

        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            return None

        center = (x1 + max_loc[0] + tw // 2, y1 + max_loc[1] + th // 2)
        return template_path.name, float(max_val), center

    def _screenshot(self) -> np.ndarray | None:
        get_screen = getattr(
            self.controller,
            "get_screen",
            getattr(self.controller, "screenshot", None),
        )
        if get_screen is None:
            return None
        return get_screen()
