from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.account_state import read_current_account
from src.config import LOG_DIR, TASK_SPECS, TAP_COOLDOWN_SECONDS
from src.exceptions import MissingAssetError
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult, Roi, write_image


@dataclass(frozen=True)
class BountyRow:
    index: int
    row_roi: Roi
    reward_roi: Roi
    star_roi: Roi
    accept_button_roi: Roi
    accept_point: tuple[int, int]


@dataclass(frozen=True)
class BountyDecision:
    row: BountyRow
    action: str
    reason: str
    stars: int
    whitelist: Optional[MatchResult] = None
    blacklist: Optional[MatchResult] = None


class BountyTask(BaseTask):
    spec = TASK_SPECS["bounty"]
    required_assets = (
        "task_label.png",
        "bounty_board_anchor.png",
        "claim_all_button.png",
        "accept_button.png",
        "accept_button2.png",
        "dispatch_all_button.png",
        "start_button.png",
        "free_refresh_label.png",
    )
    task_scene_anchors = (
        TaskSceneAnchor("bounty_board_anchor.png", threshold=0.86, roi=(560, 100, 220, 50)),
    )

    ROWS = (
        BountyRow(1, (370, 140, 565, 68), (655, 145, 82, 65), (410, 158, 180, 30), (775, 150, 150, 55), (850, 176)),
        BountyRow(2, (370, 218, 565, 68), (655, 224, 82, 65), (410, 237, 180, 30), (775, 228, 150, 55), (850, 254)),
        BountyRow(3, (370, 296, 565, 68), (655, 302, 82, 65), (410, 315, 180, 30), (775, 307, 150, 55), (850, 333)),
        BountyRow(4, (370, 376, 565, 68), (655, 382, 82, 65), (410, 395, 180, 30), (775, 386, 150, 55), (850, 411)),
    )
    CLAIM_ALL_ROI: Roi = (575, 455, 205, 70)
    FREE_REFRESH_ROI: Roi = (765, 460, 170, 65)
    DISPATCH_DIALOG_ROI: Roi = (215, 75, 530, 390)
    DISPATCH_ALL_ROI: Roi = (285, 395, 165, 65)
    START_ROI: Roi = (505, 395, 170, 65)
    REFRESH_CONFIRM_DIALOG_ROI: Roi = (230, 95, 500, 350)
    REFRESH_CONFIRM_YES_POINT = (590, 402)
    MAX_STEPS = 24
    MAX_REFRESHES = 8
    DIRECT_WHITELIST_THRESHOLD = 0.95
    NEAR_WHITELIST_THRESHOLD = 0.74
    BLACKLIST_THRESHOLD = 0.86

    def execute(self) -> str:
        claimed = 0
        accepted = 0
        refreshes = 0
        unknown = 0

        for _ in range(self.MAX_STEPS):
            screen = self.context.controller.screenshot()

            if self._tap_claim_all_if_present(screen):
                claimed += 1
                continue

            decisions = [self.plan_row(screen, row) for row in self.ROWS]
            unknown_decisions = [decision for decision in decisions if decision.action == "unknown"]
            if unknown_decisions:
                unknown += len(unknown_decisions)
                self._save_unknown_debug(screen, unknown_decisions)

            accept = next((decision for decision in decisions if decision.action == "accept"), None)
            if accept is not None:
                if self._accept_row(accept):
                    accepted += 1
                    continue
                return (
                    f"bounty completed; claimed={claimed}; accepted={accepted}; "
                    f"refreshes={refreshes}; unknown={unknown}; dispatch_unavailable=1"
                )

            if refreshes < self.MAX_REFRESHES and self._tap_free_refresh_if_present(screen):
                refreshes += 1
                continue

            return f"bounty completed; claimed={claimed}; accepted={accepted}; refreshes={refreshes}; unknown={unknown}"

        return f"bounty stopped after max steps; claimed={claimed}; accepted={accepted}; refreshes={refreshes}; unknown={unknown}"

    def plan_row(self, screen: np.ndarray, row: BountyRow) -> BountyDecision:
        stars = self.count_stars(screen, row.star_roi)
        if not self._is_accept_button_available(screen, row):
            return BountyDecision(row, "skip", "not_accept_button", stars)
        if stars < 5:
            return BountyDecision(row, "skip", "below_min_stars", stars)

        whitelist = self._best_resource_match(screen, self._resource_templates("whitelist"), row.reward_roi)
        blacklist = self._best_resource_match(screen, self._resource_templates("blacklist"), row.reward_roi)

        if (
            whitelist is not None
            and whitelist.confidence >= self.DIRECT_WHITELIST_THRESHOLD
            and (blacklist is None or whitelist.confidence >= blacklist.confidence + 0.03)
        ):
            return BountyDecision(row, "accept", "whitelist", stars, whitelist, blacklist)
        if blacklist is not None and blacklist.confidence >= self.BLACKLIST_THRESHOLD:
            return BountyDecision(row, "skip", "blacklist", stars, whitelist, blacklist)
        if (
            whitelist is not None
            and whitelist.confidence >= self.NEAR_WHITELIST_THRESHOLD
            and stars >= 6
            and (blacklist is None or whitelist.confidence >= blacklist.confidence)
        ):
            return BountyDecision(row, "accept", "near_whitelist_6_star", stars, whitelist, blacklist)
        if stars >= 5 and whitelist is None and blacklist is None:
            return BountyDecision(row, "unknown", "unknown_resource", stars, whitelist, blacklist)
        if (
            stars >= 6
            and whitelist is not None
            and whitelist.confidence >= self.NEAR_WHITELIST_THRESHOLD - 0.08
            and (blacklist is None or blacklist.confidence < self.BLACKLIST_THRESHOLD)
        ):
            return BountyDecision(row, "unknown", "low_confidence_whitelist", stars, whitelist, blacklist)
        return BountyDecision(row, "skip", "not_whitelisted", stars, whitelist, blacklist)

    def _is_accept_button_available(self, screen: np.ndarray, row: BountyRow) -> bool:
        for asset_name in ("accept_button.png", "accept_button2.png"):
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=0.82,
                roi=row.accept_button_roi,
                check_brightness=False,
            )
            if match is not None:
                return True
        return False

    @staticmethod
    def count_stars(screen: np.ndarray, roi: Roi) -> int:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return 0
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (15, 80, 120), (45, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        centers: list[float] = []
        for contour in contours:
            cx, _cy, cw, ch = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if not 6 <= cw <= 22 or not 6 <= ch <= 22 or area <= 20:
                continue
            center_x = cx + cw / 2
            if all(abs(center_x - existing) > 8 for existing in centers):
                centers.append(center_x)
        return len(centers)

    def _accept_row(self, decision: BountyDecision) -> bool:
        row = decision.row
        self.context.controller.annotate_next_tap_debug(
            lines=[
                f"bounty accept row={row.index}",
                f"reason={decision.reason} stars={decision.stars}",
                f"white={self._match_label(decision.whitelist)} black={self._match_label(decision.blacklist)}",
            ],
            boxes=[(*row.reward_roi, "roi")],
        )
        self.context.controller.tap(*row.accept_point)
        time.sleep(TAP_COOLDOWN_SECONDS)
        screen = self.context.controller.screenshot()
        if not self._tap_popup_button(screen, "dispatch_all_button.png", self.DISPATCH_ALL_ROI, "blue", "bounty dispatch all"):
            self._save_dispatch_unavailable_debug(screen, decision)
            return False
        time.sleep(TAP_COOLDOWN_SECONDS)
        screen = self.context.controller.screenshot()
        if not self._tap_popup_button(screen, "start_button.png", self.START_ROI, "yellow", "bounty dispatch start"):
            self._save_dispatch_unavailable_debug(screen, decision)
            return False
        time.sleep(TAP_COOLDOWN_SECONDS)
        self.handle_known_blocker_once()
        return True

    def _tap_claim_all_if_present(self, screen: np.ndarray) -> bool:
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("claim_all_button.png"),
            threshold=0.84,
            roi=self.CLAIM_ALL_ROI,
            check_brightness=False,
        )
        if match is None:
            return False
        self.context.controller.annotate_next_tap_debug(
            lines=[f"bounty claim all confidence={match.confidence:.3f}"],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(*match.center)
        time.sleep(TAP_COOLDOWN_SECONDS)
        self.handle_known_blocker_once()
        return True

    def _tap_free_refresh_if_present(self, screen: np.ndarray) -> bool:
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("free_refresh_label.png"),
            threshold=0.84,
            roi=self.FREE_REFRESH_ROI,
            check_brightness=False,
        )
        if match is None:
            return False
        self.context.controller.annotate_next_tap_debug(
            lines=[f"bounty free refresh confidence={match.confidence:.3f}"],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(850, 492)
        time.sleep(TAP_COOLDOWN_SECONDS)
        self._confirm_refresh_if_prompted()
        return True

    def _confirm_refresh_if_prompted(self) -> bool:
        screen = self.context.controller.screenshot()
        if not self._is_refresh_confirm_visible(screen):
            return False
        self.context.controller.annotate_next_tap_debug(
            lines=["bounty confirm free refresh"],
            boxes=[(*self.REFRESH_CONFIRM_DIALOG_ROI, "roi")],
        )
        self.context.controller.tap(*self.REFRESH_CONFIRM_YES_POINT)
        time.sleep(TAP_COOLDOWN_SECONDS)
        return True

    def _is_refresh_confirm_visible(self, screen: np.ndarray) -> bool:
        x, y, w, h = self.REFRESH_CONFIRM_DIALOG_ROI
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return False
        blue, green, red = cv2.split(crop)
        dark_ratio = float(np.count_nonzero((blue < 95) & (green < 95) & (red < 115))) / float(crop.shape[0] * crop.shape[1])
        yes_button = crop[280:335, 275:440]
        if yes_button.size == 0:
            return False
        yb, yg, yr = cv2.split(yes_button)
        blue_ratio = float(np.count_nonzero((yb > 150) & (yg > 110) & (yr < 120))) / float(yes_button.shape[0] * yes_button.shape[1])
        return dark_ratio > 0.45 and blue_ratio > 0.12

    def _tap_popup_button(self, screen: np.ndarray, asset_name: str, roi: Roi, color: str, label: str) -> bool:
        if not self._is_dispatch_dialog_visible(screen):
            return False
        match = self.context.matcher.match_template(
            screen,
            self.asset_path(asset_name),
            threshold=0.82,
            roi=roi,
            check_brightness=False,
        )
        if match is None:
            if not self._is_colored_button_visible(screen, roi, color):
                return False
            x, y, w, h = roi
            center = (x + w // 2, y + h // 2)
            self.context.controller.annotate_next_tap_debug(
                lines=[f"{label} color fallback"],
                boxes=[(*roi, "go")],
            )
            self.context.controller.tap(*center)
            return True
        self.context.controller.annotate_next_tap_debug(
            lines=[f"{label} confidence={match.confidence:.3f}"],
            boxes=[(*match.bbox, "go")],
        )
        self.context.controller.tap(*match.center)
        return True

    @staticmethod
    def _is_colored_button_visible(screen: np.ndarray, roi: Roi, color: str) -> bool:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return False
        blue, green, red = cv2.split(crop)
        if color == "blue":
            mask = (blue > 145) & (green > 115) & (red < 100)
        elif color == "yellow":
            mask = (green > 130) & (red > 170) & (blue < 90)
        else:
            raise ValueError(f"Unsupported button color: {color}")
        return float(np.count_nonzero(mask)) / float(mask.size) > 0.18

    def _is_dispatch_dialog_visible(self, screen: np.ndarray) -> bool:
        x, y, w, h = self.DISPATCH_DIALOG_ROI
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return False
        blue, green, red = cv2.split(crop)
        dark_ratio = float(np.count_nonzero((blue < 95) & (green < 95) & (red < 115))) / float(crop.shape[0] * crop.shape[1])
        return dark_ratio > 0.38

    def _best_resource_match(
        self,
        screen: np.ndarray,
        templates: list[Path],
        roi: Roi,
    ) -> Optional[MatchResult]:
        best: Optional[MatchResult] = None
        for path in templates:
            match = self.context.matcher.best_template_match(screen, path, roi=roi)
            if match is None:
                continue
            if best is None or match.confidence > best.confidence:
                best = match
        return best

    def _resource_templates(self, group: str) -> list[Path]:
        root = self.spec.asset_dir / group
        if not root.exists():
            return []
        account = read_current_account(default="default")
        templates = [path for path in root.glob("*.png") if path.is_file()]
        account_dir = root / account
        if account_dir.exists():
            templates.extend(path for path in account_dir.glob("*.png") if path.is_file())
        return sorted(templates, key=lambda path: str(path))

    def _save_unknown_debug(self, screen: np.ndarray, decisions: list[BountyDecision]) -> None:
        boxes = []
        lines = ["bounty unknown resource"]
        for decision in decisions:
            boxes.append((*decision.row.reward_roi, "roi"))
            lines.append(
                f"row={decision.row.index} stars={decision.stars} "
                f"white={self._match_label(decision.whitelist)} black={self._match_label(decision.blacklist)}"
            )
        saved = self.context.controller.save_annotated_debug(
            "bounty_unknown_resource",
            screen,
            lines=lines,
            boxes=boxes,
            panel_position="right",
        )
        if saved is not None:
            return
        self._write_fallback_debug("bounty_unknown_resource", screen, boxes=boxes, lines=lines)

    def _save_dispatch_unavailable_debug(self, screen: np.ndarray, decision: BountyDecision) -> None:
        lines = [
            "bounty dispatch unavailable",
            f"row={decision.row.index} stars={decision.stars} reason={decision.reason}",
            f"white={self._match_label(decision.whitelist)} black={self._match_label(decision.blacklist)}",
        ]
        boxes = [(*decision.row.reward_roi, "roi")]
        saved = self.context.controller.save_annotated_debug(
            "bounty_dispatch_unavailable",
            screen,
            lines=lines,
            boxes=boxes,
            panel_position="right",
        )
        if saved is None:
            self._write_fallback_debug("bounty_dispatch_unavailable", screen, boxes=boxes, lines=lines)

    def _write_fallback_debug(
        self,
        label: str,
        screen: np.ndarray,
        *,
        boxes: list[tuple[int, int, int, int, str]],
        lines: list[str],
    ) -> Path:
        image = screen.copy()
        for x, y, w, h, kind in boxes:
            color = (255, 255, 0) if kind == "roi" else (255, 255, 255)
            cv2.rectangle(image, (x, y), (x + w, y + h), color, 2)
        for index, line in enumerate(lines[:8]):
            cv2.putText(image, line[:80], (12, 25 + index * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        path = LOG_DIR / f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        return write_image(path, image)

    @staticmethod
    def _match_label(match: Optional[MatchResult]) -> str:
        if match is None:
            return "none"
        return f"{match.template_path.name}:{match.confidence:.3f}"
