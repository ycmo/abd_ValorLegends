from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from src.config import TASK_SPECS, TAP_COOLDOWN_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.task_runner import BaseTask, TaskRunResult, TaskSceneAnchor, TaskState
from src.vision_matcher import Roi


WILD_TREASURE_START_CHOICES = (
    "full",
    "hero-upgrade",
    "explore",
    "skip-upgrade",
    "battle-setup",
    "victory",
    "activation",
)
_WILD_TREASURE_START_OVERRIDE: str | None = None


def set_wild_treasure_start_override(start: str | None) -> None:
    global _WILD_TREASURE_START_OVERRIDE
    if start is not None and start not in WILD_TREASURE_START_CHOICES:
        raise ValueError(f"Unsupported Wild Treasure start point: {start}")
    _WILD_TREASURE_START_OVERRIDE = start


@dataclass(frozen=True)
class WildTreasurePoint:
    label: str
    point: tuple[int, int]


class WildTreasureTask(BaseTask):
    spec = TASK_SPECS["wild_treasure"]
    required_assets = (
        "map_all_harvest_button.png",
        "map_hero_button.png",
        "hero_list_title.png",
        "hero_info_title.png",
        "upgrade_button.png",
        "ascend_button.png",
        "ascend_dialog_title.png",
        "ascend_confirm_button.png",
        "battle_challenge_button.png",
        "battle_event_target.png",
        "victory_title.png",
        "continue_text.png",
        "activation_success_title.png",
        "activation_go_button.png",
    )

    MAP_ANCHOR_ROI: Roi = (45, 440, 155, 60)
    HERO_LIST_TITLE_ROI: Roi = (350, 0, 260, 55)
    HERO_INFO_TITLE_ROI: Roi = (70, 0, 240, 55)
    ASCEND_BUTTON_ROI: Roi = (700, 430, 230, 90)
    ASCEND_DIALOG_TITLE_ROI: Roi = (330, 40, 300, 80)
    ASCEND_CONFIRM_BUTTON_ROI: Roi = (380, 430, 220, 90)
    BATTLE_CHALLENGE_ROI: Roi = (820, 400, 140, 140)
    BATTLE_EVENT_TARGET_ROI: Roi = (250, 80, 430, 270)
    EXPLORE_TILE_SEARCH_ROI: Roi = (240, 80, 520, 320)
    VICTORY_TITLE_ROI: Roi = (360, 85, 230, 120)
    ACTIVATION_SUCCESS_ROI: Roi = (470, 115, 240, 95)

    INITIAL_EVENT = WildTreasurePoint("initial_event", (393, 165))
    HERO_BUTTON = WildTreasurePoint("hero_button", (916, 503))
    HERO_LIST_BACK = WildTreasurePoint("hero_list_back", (51, 20))
    HERO_INFO_BACK = WildTreasurePoint("hero_info_back", (48, 20))
    HERO_CARDS = (
        WildTreasurePoint("hero_1", (75, 76)),
        WildTreasurePoint("hero_2", (166, 76)),
    )
    UPGRADE_BUTTON = WildTreasurePoint("upgrade_button", (790, 480))
    ASCEND_BUTTON = WildTreasurePoint("ascend_button", (795, 480))
    ASCEND_CONFIRM_BUTTON = WildTreasurePoint("ascend_confirm_button", (481, 479))
    BATTLE_EVENT = WildTreasurePoint("battle_event", (474, 240))
    FORMATION_HEROES = (
        WildTreasurePoint("formation_hero_1", (55, 476)),
        WildTreasurePoint("formation_hero_2", (145, 476)),
        WildTreasurePoint("formation_hero_3", (235, 476)),
        WildTreasurePoint("formation_hero_4", (325, 476)),
    )
    CHALLENGE_BUTTON = WildTreasurePoint("challenge_button", (910, 485))
    CONTINUE_BUTTON = WildTreasurePoint("continue_button", (480, 487))
    ACTIVATION_GO_BUTTON = WildTreasurePoint("activation_go_button", (594, 361))

    UPGRADE_LONG_PRESS_MS = 6000
    SCENE_WAIT_SECONDS = 12.0
    BATTLE_WAIT_SECONDS = 90.0
    MAX_UPGRADE_ASCENDS = 3
    MAX_EXPLORE_STEPS = 12

    task_scene_anchors = (
        TaskSceneAnchor("map_all_harvest_button.png", threshold=0.86, roi=MAP_ANCHOR_ROI),
    )

    def run(self) -> TaskRunResult:
        return self._run_independent(require_current_scene=True)

    def run_from_current_scene(self) -> TaskRunResult:
        return self._run_independent(require_current_scene=True)

    def _run_independent(self, *, require_current_scene: bool) -> TaskRunResult:
        started = time.time()
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(path) for path in missing),
                started,
            )
        try:
            if require_current_scene and not self.is_current_resume_scene():
                raise TaskFailedError(f"Current screen is not the {self.spec.display_name} task scene")
            return self._result(TaskState.COMPLETED, self.execute(), started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except (BotError, TaskFailedError) as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        start = self.start_point()
        if start == "full":
            self._run_initial_event()
            self._run_upgrade_and_after()
        elif start == "hero-upgrade":
            self._run_upgrade_and_after()
        elif start in {"explore", "skip-upgrade"}:
            self._run_explore_and_after()
        elif start == "battle-setup":
            self._run_battle_setup_and_after()
        elif start == "victory":
            self._run_victory_and_after()
        elif start == "activation":
            self._run_activation_and_after()
        else:
            raise TaskFailedError(f"Unsupported Wild Treasure start point: {start}")
        return f"wild treasure completed from {start}"

    def start_point(self) -> str:
        return _WILD_TREASURE_START_OVERRIDE or "full"

    def is_current_resume_scene(self) -> bool:
        screen = self.context.controller.screenshot()
        start = self.start_point()
        if start in {"full", "hero-upgrade", "explore", "skip-upgrade"}:
            return self.is_task_scene(screen)
        if start == "battle-setup":
            return self.is_battle_setup_visible(screen)
        if start == "victory":
            return self.is_victory_visible(screen)
        if start == "activation":
            return self.is_activation_success_visible(screen)
        return False

    def _run_initial_event(self) -> None:
        self._tap_point(self.INITIAL_EVENT)
        self._wait_for_map_or_clear_blockers()

    def _run_upgrade_and_after(self) -> None:
        self._upgrade_first_two_heroes()
        self._run_explore_and_after()

    def _run_explore_and_after(self) -> None:
        battle_started = self._explore_until_battle_event()
        if not battle_started:
            self._tap_battle_event()
            self._wait_for_scene("battle", self.is_battle_setup_visible, timeout_seconds=self.SCENE_WAIT_SECONDS)
        self._run_battle_setup_and_after()

    def _run_battle_setup_and_after(self) -> None:
        for hero in self.FORMATION_HEROES:
            self._tap_point(hero, wait_seconds=0.25)
        self._tap_point(self.CHALLENGE_BUTTON)
        self._wait_for_scene("victory", self.is_victory_visible, timeout_seconds=self.BATTLE_WAIT_SECONDS)
        self._run_victory_and_after()

    def _run_victory_and_after(self) -> None:
        self._tap_point(self.CONTINUE_BUTTON)
        self._wait_for_scene(
            "activation success",
            self.is_activation_success_visible,
            timeout_seconds=self.SCENE_WAIT_SECONDS,
        )
        self._run_activation_and_after()

    def _run_activation_and_after(self) -> None:
        self._tap_point(self.ACTIVATION_GO_BUTTON)
        self._wait_for_scene("wild treasure map", self.is_task_scene, timeout_seconds=self.SCENE_WAIT_SECONDS)

    def _upgrade_first_two_heroes(self) -> None:
        self._open_hero_list()
        for hero in self.HERO_CARDS:
            self._tap_point(hero)
            self._wait_for_scene("hero info", self.is_hero_info_visible, timeout_seconds=self.SCENE_WAIT_SECONDS)
            self._upgrade_current_hero_to_limit()
            self._tap_point(self.HERO_INFO_BACK)
            self._wait_for_scene("hero list", self.is_hero_list_visible, timeout_seconds=self.SCENE_WAIT_SECONDS)
        self._tap_point(self.HERO_LIST_BACK)
        self._wait_for_scene("wild treasure map", self.is_task_scene, timeout_seconds=self.SCENE_WAIT_SECONDS)

    def _open_hero_list(self) -> None:
        for attempt in range(1, 4):
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                continue
            if self.is_hero_list_visible(screen):
                return
            if not self.is_task_scene(screen):
                time.sleep(0.5)
                continue
            self._log(f"Wild Treasure open hero list attempt {attempt}/3")
            self._tap_point(self.HERO_BUTTON)
            if self._wait_for_hero_list_or_map_after_entry():
                return
        raise TaskFailedError("Wild Treasure expected scene not found: hero list")

    def _wait_for_hero_list_or_map_after_entry(self) -> bool:
        deadline = time.time() + self.SCENE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_hero_list_visible(screen):
                return True
            if self.is_task_scene(screen):
                return False
            time.sleep(0.5)
        return False

    def _upgrade_current_hero_to_limit(self) -> None:
        for index in range(self.MAX_UPGRADE_ASCENDS + 1):
            self._long_press_point(self.UPGRADE_BUTTON, duration_ms=self.UPGRADE_LONG_PRESS_MS)
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                continue
            if not self.is_ascend_available(screen):
                return
            if index >= self.MAX_UPGRADE_ASCENDS:
                raise TaskFailedError("Wild Treasure hero still needs ascend after maximum upgrade loops")
            self._tap_point(self.ASCEND_BUTTON)
            self._wait_for_scene("ascend dialog", self.is_ascend_dialog_visible, timeout_seconds=self.SCENE_WAIT_SECONDS)
            self._tap_point(self.ASCEND_CONFIRM_BUTTON)
            self._wait_for_scene("hero info after ascend", self.is_hero_info_visible, timeout_seconds=self.SCENE_WAIT_SECONDS)

    def _explore_until_battle_event(self) -> bool:
        for step in range(1, self.MAX_EXPLORE_STEPS + 1):
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                continue
            if self.find_battle_event(screen) is not None:
                return False
            if not self.is_task_scene(screen):
                if self.is_battle_setup_visible(screen):
                    return True
                time.sleep(0.5)
                continue
            explore_point = self.find_explore_tile(screen)
            if explore_point is None:
                raise TaskFailedError("Wild Treasure lit exploration tile was not found")
            self._log(f"Wild Treasure explore map step {step}/{self.MAX_EXPLORE_STEPS}")
            self._tap_point(WildTreasurePoint("explore_tile", explore_point))
            outcome = self._wait_after_explore_action()
            if outcome == "battle":
                return True
            if self.find_battle_event(self.context.controller.screenshot()) is not None:
                return False
        raise TaskFailedError("Wild Treasure battle event target was not found after exploring the map")

    def _wait_after_explore_action(self) -> str:
        deadline = time.time() + self.SCENE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_battle_setup_visible(screen):
                return "battle"
            if self.is_task_scene(screen):
                return "map"
            time.sleep(0.5)
        raise TaskFailedError("Wild Treasure did not reach map or battle after exploring")

    def _tap_battle_event(self) -> None:
        screen = self.context.controller.screenshot()
        match = self.find_battle_event(screen)
        if match is None:
            raise TaskFailedError("Wild Treasure battle event target is not visible")
        point = WildTreasurePoint("battle_event", self._battle_event_tap_point(match))
        self._tap_point(point)

    @staticmethod
    def _battle_event_tap_point(match) -> tuple[int, int]:
        x, y, width, height = match.bbox
        return (x + width // 2, y + height - 8)

    def _wait_for_map_or_clear_blockers(self) -> None:
        deadline = time.time() + self.SCENE_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if self.is_task_scene(screen):
                return
            time.sleep(0.5)
        raise TaskFailedError("Wild Treasure map did not return after event reward")

    def _wait_for_scene(self, label: str, predicate, *, timeout_seconds: float) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if self.handle_known_blocker_before_scan(screen):
                time.sleep(0.2)
                continue
            if predicate(screen):
                return
            time.sleep(0.5)
        raise TaskFailedError(f"Wild Treasure expected scene not found: {label}")

    def is_hero_list_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "hero_list_title.png", self.HERO_LIST_TITLE_ROI, threshold=0.88)

    def is_hero_info_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "hero_info_title.png", self.HERO_INFO_TITLE_ROI, threshold=0.88)

    def is_battle_setup_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "battle_challenge_button.png", self.BATTLE_CHALLENGE_ROI, threshold=0.86)

    def is_ascend_available(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "ascend_button.png", self.ASCEND_BUTTON_ROI, threshold=0.86)

    def is_ascend_dialog_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "ascend_dialog_title.png", self.ASCEND_DIALOG_TITLE_ROI, threshold=0.86)

    def find_battle_event(self, screen: np.ndarray):
        return self.context.matcher.match_template(
            screen,
            self.asset_path("battle_event_target.png"),
            threshold=0.86,
            roi=self.BATTLE_EVENT_TARGET_ROI,
            check_brightness=False,
        )

    def find_explore_tile(self, screen: np.ndarray) -> tuple[int, int] | None:
        import cv2

        x, y, width, height = self.EXPLORE_TILE_SEARCH_ROI
        crop = screen[y : y + height, x : x + width]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([8, 45, 145]), np.array([42, 255, 255]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[tuple[float, tuple[int, int]]] = []
        for contour in contours:
            cx, cy, cw, ch = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if not (700 <= area <= 14000 and 35 <= cw <= 210 and 28 <= ch <= 150):
                continue
            fill_ratio = float(np.count_nonzero(mask[cy : cy + ch, cx : cx + cw])) / float(cw * ch)
            if not 0.25 <= fill_ratio <= 1.00:
                continue
            abs_center = (x + cx + cw // 2, y + cy + ch // 2)
            if abs_center[0] < 350 or abs_center[1] < 120:
                continue
            # The mainline target is toward the upper-left bridge. Prefer lit frontier
            # tiles in that direction, while avoiding lower terrain highlights.
            score = abs(abs_center[0] - 420) + abs(abs_center[1] - 170) + max(0, abs_center[1] - 240) * 2
            candidates.append((score, abs_center))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    def is_victory_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "victory_title.png", self.VICTORY_TITLE_ROI, threshold=0.86)

    def is_activation_success_visible(self, screen: np.ndarray) -> bool:
        return self._match_asset(screen, "activation_success_title.png", self.ACTIVATION_SUCCESS_ROI, threshold=0.86)

    def _match_asset(self, screen: np.ndarray, asset_name: str, roi: Roi, *, threshold: float) -> bool:
        return self.context.matcher.match_template(
            screen,
            self.asset_path(asset_name),
            threshold=threshold,
            roi=roi,
            check_brightness=False,
        ) is not None

    def _tap_point(self, point: WildTreasurePoint, *, wait_seconds: float = TAP_COOLDOWN_SECONDS) -> None:
        x, y = point.point
        self._log(f"Wild Treasure tap {point.label}: ({x}, {y})")
        self.context.controller.annotate_next_tap_debug(lines=[f"wild_treasure {point.label}"])
        self.context.controller.tap(x, y)
        time.sleep(wait_seconds)

    def _long_press_point(self, point: WildTreasurePoint, *, duration_ms: int) -> None:
        x, y = point.point
        self._log(f"Wild Treasure long press {point.label}: ({x}, {y}) {duration_ms}ms")
        self.context.controller.annotate_next_tap_debug(
            lines=[f"wild_treasure long_press {point.label} {duration_ms}ms"]
        )
        self.context.controller.long_press(x, y, duration_ms=duration_ms)
        time.sleep(TAP_COOLDOWN_SECONDS)
