from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from src.config import TASK_SPECS, TAP_COOLDOWN_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.task_runner import BaseTask, TaskRunResult, TaskSceneAnchor, TaskState
from src.vision_matcher import MatchResult, Roi


_HERO_REROLL_TARGET_COUNT = 1


def set_hero_reroll_target_count(count: int | None) -> None:
    global _HERO_REROLL_TARGET_COUNT
    if count is None:
        _HERO_REROLL_TARGET_COUNT = 1
        return
    if count < 1:
        raise ValueError("--target-count must be >= 1")
    _HERO_REROLL_TARGET_COUNT = count


@dataclass(frozen=True)
class HeroRerollPoint:
    label: str
    point: tuple[int, int]


class HeroRerollLoopTask(BaseTask):
    spec = TASK_SPECS["hero_reroll_loop"]
    required_assets = (
        "hero_list_title.png",
        "hero_info_title.png",
        "target_dabi_card.png",
        "target_dabi_face.png",
        "awaken_tab.png",
        "awaken_button.png",
        "awaken_success_title.png",
        "material_dialog_title.png",
        "material_confirm_button.png",
        "soul_sacrifice_title.png",
        "hero_info_reset_button.png",
        "hero_reset_tab.png",
        "reset_execute_button.png",
        "reset_confirm_title.png",
        "reset_confirm_button.png",
    )

    HERO_LIST_TITLE_ROI: Roi = (375, 0, 225, 52)
    HERO_LIST_GRID_ROI: Roi = (15, 41, 885, 203)
    HERO_INFO_TITLE_ROI: Roi = (67, 0, 172, 52)
    AWAKEN_BUTTON_ROI: Roi = (615, 420, 337, 90)
    MATERIAL_DIALOG_TITLE_ROI: Roi = (270, 15, 420, 71)
    MATERIAL_DIALOG_ROI: Roi = (112, 71, 735, 375)
    AWAKEN_SUCCESS_ROI: Roi = (322, 390, 330, 97)
    SOUL_SACRIFICE_TITLE_ROI: Roi = (52, 0, 195, 52)
    RESET_CONFIRM_TITLE_ROI: Roi = (322, 90, 315, 67)

    AWAKEN_TAB = HeroRerollPoint("awaken_tab", (58, 168))
    HERO_INFO_RESET = HeroRerollPoint("hero_info_reset", (585, 168))
    RESET_EXECUTE = HeroRerollPoint("reset_execute", (251, 495))
    RESET_CONFIRM = HeroRerollPoint("reset_confirm", (589, 401))
    BACK = HeroRerollPoint("back", (31, 21))
    AWAKEN_SUCCESS_CONTINUE = HeroRerollPoint("awaken_success_continue", (836, 506))
    MATERIAL_CONFIRM = HeroRerollPoint("material_confirm", (480, 469))
    HERO_RESET_FIRST_CANDIDATE = HeroRerollPoint("hero_reset_first_candidate", (558, 122))

    MATERIAL_CARD_CENTERS = (
        (177, 132),
        (262, 132),
        (349, 132),
        (435, 132),
        (520, 132),
        (606, 132),
        (691, 132),
        (777, 132),
        (177, 222),
        (262, 222),
        (349, 222),
        (435, 222),
        (520, 222),
        (606, 222),
        (691, 222),
        (777, 222),
    )
    HERO_LIST_CARD_CENTERS = (
        (75, 91),
        (165, 91),
        (255, 91),
        (345, 91),
        (435, 91),
        (525, 91),
        (615, 91),
        (705, 91),
        (795, 91),
        (885, 91),
        (75, 181),
        (165, 181),
        (255, 181),
        (345, 181),
        (435, 181),
        (525, 181),
        (615, 181),
        (705, 181),
    )

    PAGE_WAIT_SECONDS = 10.0
    MAX_OUTER_LOOPS = 40
    MAX_AWAKEN_STEPS_PER_LOOP = 1
    MAX_MATERIAL_SELECTIONS = 8
    TARGET_MATCH_THRESHOLD = 0.88
    TARGET_FACE_MATCH_THRESHOLD = 0.86
    YELLOW_FIVE_STAR_THRESHOLD = 0.18
    DUPLICATE_HERO_SIMILARITY_THRESHOLD = 0.90

    task_scene_anchors = (
        TaskSceneAnchor("hero_list_title.png", threshold=0.86, roi=HERO_LIST_TITLE_ROI),
        TaskSceneAnchor("hero_info_title.png", threshold=0.86, roi=HERO_INFO_TITLE_ROI),
        TaskSceneAnchor("soul_sacrifice_title.png", threshold=0.86, roi=SOUL_SACRIFICE_TITLE_ROI),
    )

    def run(self) -> TaskRunResult:
        return self._run_independent()

    def run_from_current_scene(self) -> TaskRunResult:
        return self._run_independent()

    def _run_independent(self) -> TaskRunResult:
        started = time.time()
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(path) for path in missing),
                started,
            )
        try:
            if not self.is_current_task_scene():
                raise TaskFailedError(f"Current screen is not the {self.spec.display_name} task scene")
            return self._result(TaskState.COMPLETED, self.execute(), started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except (BotError, TaskFailedError) as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def is_current_task_scene(self) -> bool:
        screen = self.context.controller.screenshot()
        return (
            self.is_task_scene(screen)
            or self.is_material_dialog_visible(screen)
            or self.is_reset_confirm_visible(screen)
        )

    def execute(self) -> str:
        target_count = _HERO_REROLL_TARGET_COUNT
        for loop_index in range(1, self.MAX_OUTER_LOOPS + 1):
            self._ensure_hero_list()
            screen = self.context.controller.screenshot()
            current_count = self.count_target_heroes(screen)
            self._log(f"Hero reroll target count {current_count}/{target_count}")
            if current_count >= target_count:
                return f"target reached: {current_count}/{target_count}"

            self._open_starter_from_list(screen)
            awaken_steps = self._awaken_until_blocked()
            if awaken_steps < 1:
                raise TaskFailedError("Hero reroll awaken did not complete; refusing to reset")
            self._reset_current_target()
            self._log(f"Hero reroll loop {loop_index}: awaken_steps={awaken_steps}")

        raise TaskFailedError("Hero reroll did not reach target count before loop limit")

    def count_target_heroes(self, screen: np.ndarray | None = None) -> int:
        if screen is None:
            screen = self.context.controller.screenshot()
        return len(
            self.context.matcher.match_template_all(
                screen,
                self.asset_path("target_dabi_card.png"),
                threshold=self.TARGET_MATCH_THRESHOLD,
                roi=self.HERO_LIST_GRID_ROI,
                check_brightness=False,
                max_results=80,
                min_center_distance=55,
            )
        )

    def _open_starter_from_list(self, screen: np.ndarray) -> None:
        target_matches = self._target_matches_on_list(screen)
        if len(target_matches) >= 2:
            target = sorted(target_matches, key=lambda match: (match.center[1], match.center[0]))[0]
            self._current_starter_identity = self._card_identity_crop(screen, target.center)
            self._current_starter_is_target = True
            self._tap_point(HeroRerollPoint("open_target_hero", target.center))
            self._wait_for_scene("hero info", self.is_hero_info_visible)
            return

        starter = self._find_duplicate_yellow_five_star_starter(screen)
        if starter is None:
            raise TaskFailedError("Hero reroll found neither two target heroes nor another duplicate yellow five-star hero")
        self._current_starter_identity = self._card_identity_crop(screen, starter.center)
        self._current_starter_is_target = False
        self._tap_point(HeroRerollPoint("open_duplicate_yellow_hero", starter.center))
        self._wait_for_scene("hero info", self.is_hero_info_visible)

    def _target_matches_on_list(self, screen: np.ndarray) -> list[MatchResult]:
        matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("target_dabi_card.png"),
            threshold=self.TARGET_MATCH_THRESHOLD,
            roi=self.HERO_LIST_GRID_ROI,
            check_brightness=False,
            max_results=20,
            min_center_distance=55,
        )
        return list(matches)

    def _find_duplicate_yellow_five_star_starter(self, screen: np.ndarray) -> MatchResult | None:
        candidates = [
            center
            for center in self.HERO_LIST_CARD_CENTERS
            if self._is_yellow_five_star_card(screen, center)
        ]
        for index, center in enumerate(candidates):
            identity = self._card_identity_crop(screen, center)
            if identity is None:
                continue
            for other in candidates[index + 1 :]:
                other_identity = self._card_identity_crop(screen, other)
                if other_identity is None:
                    continue
                if self._card_identity_similarity(identity, other_identity) >= self.DUPLICATE_HERO_SIMILARITY_THRESHOLD:
                    return MatchResult(
                        self.asset_path("target_dabi_card.png"),
                        1.0,
                        center,
                        (center[0] - 34, center[1] - 41, 68, 79),
                    )
        return None

    def _awaken_until_blocked(self) -> int:
        steps = 0
        for _ in range(self.MAX_AWAKEN_STEPS_PER_LOOP):
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                continue
            if not self.is_hero_info_visible(screen):
                self._wait_for_scene("hero info", self.is_hero_info_visible)
            self._tap_point(self.AWAKEN_TAB, wait_seconds=0.4)
            self._ensure_same_name_material_filled()
            filled = self._fill_visible_material_slot()
            screen = self.context.controller.screenshot()
            if self._find_active_material_slot(screen) is not None:
                raise TaskFailedError("Hero reroll material slot is still empty; refusing to tap awaken")
            if not self._tap_awaken_button_if_visible():
                return steps if filled else steps
            outcome = self._wait_after_awaken_tap()
            if outcome == "material":
                self._resolve_material_dialog(2)
                self._wait_after_material_confirm()
                steps += 1
                continue
            if outcome == "success":
                self._dismiss_awaken_success()
                steps += 1
                continue
            return steps
        return steps

    def _tap_awaken_button_if_visible(self) -> bool:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("awaken_button.png"),
            threshold=0.82,
            roi=self.AWAKEN_BUTTON_ROI,
            check_brightness=False,
        )
        if match is None:
            return False
        self._tap_point(HeroRerollPoint("awaken_button", match.center))
        return True

    def _tap_confirm_button_if_visible(self, label: str) -> bool:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path("reset_confirm_button.png"),
            threshold=0.86,
            roi=(480, 360, 225, 82),
            check_brightness=False,
        )
        if match is None:
            return False
        self._tap_point(HeroRerollPoint(label, match.center), wait_seconds=0.2)
        return True

    def _fill_visible_material_slot(self) -> int:
        screen = self.context.controller.screenshot()
        if not self.is_hero_info_visible(screen):
            return 0
        slot = self._find_active_material_slot(screen)
        if slot is None:
            return 0
        point, required_count = slot
        if not self._open_material_dialog_from_slot(HeroRerollPoint("awaken_material_slot", point)):
            return 0
        self._resolve_material_dialog(required_count)
        self._wait_after_material_confirm()
        self._tap_point(self.AWAKEN_TAB, wait_seconds=0.4)
        return required_count

    def _find_active_material_slot(self, screen: np.ndarray) -> tuple[tuple[int, int], int] | None:
        if self._slot_has_blue_plus(screen, (839, 306)):
            return (839, 319), 2
        return None

    def _ensure_same_name_material_filled(self) -> None:
        screen = self.context.controller.screenshot()
        if self._slot_has_blue_plus(screen, (735, 306)):
            raise TaskFailedError(
                "Hero reroll same-name material is empty; starter duplicate was not auto-filled"
            )

    @staticmethod
    def _slot_has_blue_plus(screen: np.ndarray, center: tuple[int, int]) -> bool:
        x, y = center
        crop = screen[max(0, y - 22) : y + 22, max(0, x - 22) : x + 22]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue_gray = cv2.inRange(hsv, np.array([85, 20, 100]), np.array([130, 220, 255]))
        ratio = float(np.count_nonzero(blue_gray)) / float(blue_gray.size)
        mean_value = float(np.mean(hsv[:, :, 2]))
        return ratio >= 0.12 and mean_value < 125.0

    @staticmethod
    def _find_material_plus_centers(screen: np.ndarray) -> list[tuple[int, int]]:
        x, y, width, height = (680, 250, 230, 120)
        crop = screen[y : y + height, x : x + width]
        if crop.size == 0:
            return []
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([85, 20, 120]), np.array([125, 180, 255]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: list[tuple[int, int]] = []
        for contour in contours:
            cx, cy, cw, ch = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if 220 <= area <= 1500 and 12 <= cw <= 45 and 12 <= ch <= 45:
                centers.append((x + cx + cw // 2, y + cy + ch // 2))
        return centers

    def _open_material_dialog_from_slot(self, slot: HeroRerollPoint) -> bool:
        self._tap_point(slot)
        deadline = time.time() + self.PAGE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_material_dialog_visible(screen):
                return True
            if not self.is_hero_info_visible(screen):
                time.sleep(0.5)
                continue
            time.sleep(0.5)
        return False

    def _wait_after_awaken_tap(self) -> str:
        deadline = time.time() + self.PAGE_WAIT_SECONDS
        ignore_hero_info_until = time.time() + 4.0
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self._tap_confirm_button_if_visible("awaken_confirm"):
                deadline = max(deadline, time.time() + self.PAGE_WAIT_SECONDS)
                ignore_hero_info_until = time.time() + 4.0
                time.sleep(1.0)
                continue
            if self.is_material_dialog_visible(screen):
                return "material"
            if self.is_awaken_success_visible(screen):
                return "success"
            if self.is_hero_info_visible(screen) and time.time() >= ignore_hero_info_until:
                return "hero_info"
            time.sleep(0.5)
        return "unknown"

    def _resolve_material_dialog(self, required_count: int) -> None:
        selected_centers: set[tuple[int, int]] = set()
        for _ in range(required_count):
            screen = self.context.controller.screenshot()
            if not self.is_material_dialog_visible(screen):
                raise TaskFailedError("Hero reroll material dialog closed before enough materials were selected")
            candidate = self._find_material_candidate(screen, selected_centers)
            if candidate is None:
                raise TaskFailedError("Hero reroll eligible material not found")
            selected_centers.add(candidate.center)
            self._tap_point(HeroRerollPoint("select_material", candidate.center), wait_seconds=0.4)
        self._tap_point(self.MATERIAL_CONFIRM)

    def _find_material_candidate(
        self,
        screen: np.ndarray,
        selected_centers: set[tuple[int, int]],
    ) -> MatchResult | None:
        target_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("target_dabi_face.png"),
            threshold=self.TARGET_FACE_MATCH_THRESHOLD,
            roi=self.MATERIAL_DIALOG_ROI,
            check_brightness=False,
            max_results=10,
            min_center_distance=55,
        )
        excluded_targets = {match.center for match in target_matches}

        yellow_candidates = [
            center
            for center in self.MATERIAL_CARD_CENTERS
            if center not in selected_centers
            and not self._is_near_any(center, excluded_targets)
            and self._is_yellow_five_star_card(screen, center)
        ]
        if not yellow_candidates:
            return None
        center = sorted(yellow_candidates, key=lambda item: (item[1], item[0]))[0]
        return MatchResult(self.asset_path("target_dabi_card.png"), 1.0, center, (center[0] - 34, center[1] - 41, 68, 79))

    def _is_yellow_five_star_card(self, screen: np.ndarray, center: tuple[int, int]) -> bool:
        x, y = center
        x1 = max(0, x - 38)
        y1 = max(0, y - 41)
        card = screen[y1 : y1 + 79, x1 : x1 + 68]
        if card.size == 0:
            return False
        h, w = card.shape[:2]
        band = card[int(h * 0.68) : int(h * 0.96), int(w * 0.05) : int(w * 0.95)]
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([15, 80, 120]), np.array([42, 255, 255]))
        yellow_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        return yellow_ratio >= self.YELLOW_FIVE_STAR_THRESHOLD

    @staticmethod
    def _card_identity_crop(screen: np.ndarray, center: tuple[int, int]) -> np.ndarray | None:
        x, y = center
        x1 = max(0, x - 27)
        y1 = max(0, y - 31)
        crop = screen[y1 : y1 + 45, x1 : x1 + 54]
        if crop.shape[:2] != (45, 54):
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (48, 48), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _card_identity_similarity(first: np.ndarray, second: np.ndarray) -> float:
        result = cv2.matchTemplate(first, second, cv2.TM_CCOEFF_NORMED)
        return float(result[0][0])

    @staticmethod
    def _is_near_any(center: tuple[int, int], others: set[tuple[int, int]], *, distance: int = 18) -> bool:
        distance_sq = distance * distance
        return any((center[0] - other[0]) ** 2 + (center[1] - other[1]) ** 2 <= distance_sq for other in others)

    def _wait_after_material_confirm(self) -> None:
        deadline = time.time() + 20.0
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_awaken_success_visible(screen):
                self._dismiss_awaken_success()
                return
            if self.is_hero_info_visible(screen):
                return
            time.sleep(0.5)
        raise TaskFailedError("Hero reroll did not return after material selection")

    def _dismiss_awaken_success(self) -> None:
        deadline = time.time() + self.PAGE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.is_hero_info_visible(screen):
                return
            self._tap_point(self.AWAKEN_SUCCESS_CONTINUE, wait_seconds=1.0)
        raise TaskFailedError("Hero reroll awaken success screen did not close")

    def _reset_current_target(self) -> None:
        screen = self.context.controller.screenshot()
        if self.is_awaken_success_visible(screen):
            self._dismiss_awaken_success()
            screen = self.context.controller.screenshot()
        if not self.is_hero_info_visible(screen):
            self._wait_for_scene("hero info", self.is_hero_info_visible)
        self._tap_point(self.HERO_INFO_RESET)
        self._wait_for_scene("soul sacrifice", self.is_soul_sacrifice_visible)
        self._tap_asset_center("hero_reset_tab.png", (0, 80, 130, 130), "hero_reset_tab")
        self._tap_point(self.HERO_RESET_FIRST_CANDIDATE)
        self._tap_asset_center("reset_execute_button.png", (135, 442, 240, 90), "reset_execute")
        self._wait_for_scene("reset confirm", self.is_reset_confirm_visible)
        self._tap_asset_center("reset_confirm_button.png", (480, 360, 225, 82), "reset_confirm")
        self._wait_for_hero_list_after_reset()

    def _wait_for_hero_list_after_reset(self) -> None:
        deadline = time.time() + 25.0
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_hero_list_visible(screen):
                return
            if self.is_soul_sacrifice_visible(screen):
                self._tap_point(self.BACK)
                time.sleep(1.0)
                continue
            time.sleep(0.5)
        raise TaskFailedError("Hero reroll did not return to hero list after reset")

    def _ensure_hero_list(self) -> None:
        deadline = time.time() + self.PAGE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_hero_list_visible(screen):
                return
            if self.is_hero_info_visible(screen) or self.is_soul_sacrifice_visible(screen):
                self._tap_point(self.BACK)
                time.sleep(1.0)
                continue
            time.sleep(0.5)
        raise TaskFailedError("Hero reroll expected hero list")

    def is_hero_list_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "hero_list_title.png", self.HERO_LIST_TITLE_ROI, threshold=0.86)

    def is_hero_info_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "hero_info_title.png", self.HERO_INFO_TITLE_ROI, threshold=0.86)

    def is_material_dialog_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "material_dialog_title.png", self.MATERIAL_DIALOG_TITLE_ROI, threshold=0.86)

    def is_awaken_success_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "awaken_success_title.png", self.AWAKEN_SUCCESS_ROI, threshold=0.82)

    def is_soul_sacrifice_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "soul_sacrifice_title.png", self.SOUL_SACRIFICE_TITLE_ROI, threshold=0.86)

    def is_reset_confirm_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "reset_confirm_title.png", self.RESET_CONFIRM_TITLE_ROI, threshold=0.86)

    def _match_asset(self, screen: np.ndarray, asset_name: str, roi: Roi, *, threshold: float) -> bool:
        return (
            self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=threshold,
                roi=roi,
                check_brightness=False,
            )
            is not None
        )

    def _tap_asset_center(self, asset_name: str, roi: Roi, label: str) -> None:
        screen = self.context.controller.screenshot()
        match = self.context.matcher.match_template(
            screen,
            self.asset_path(asset_name),
            threshold=0.82,
            roi=roi,
            check_brightness=False,
        )
        if match is None:
            raise TaskFailedError(f"Hero reroll expected button not found: {asset_name}")
        self._tap_point(HeroRerollPoint(label, match.center))

    def _wait_for_scene(self, label: str, predicate, *, timeout_seconds: float | None = None) -> None:
        deadline = time.time() + (self.PAGE_WAIT_SECONDS if timeout_seconds is None else timeout_seconds)
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if predicate(screen):
                return
            time.sleep(0.5)
        raise TaskFailedError(f"Hero reroll expected scene not found: {label}")

    def _tap_point(self, point: HeroRerollPoint, *, wait_seconds: float = TAP_COOLDOWN_SECONDS) -> None:
        x, y = point.point
        self._log(f"Hero reroll tap {point.label}: ({x}, {y})")
        self.context.controller.annotate_next_tap_debug(lines=[f"hero_reroll {point.label}"])
        self.context.controller.tap(x, y)
        time.sleep(wait_seconds)
