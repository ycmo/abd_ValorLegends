from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np
from ads2.core.runner import ReactiveRunner

from src.config import EXPECTED_SCREEN_SIZE, TASK_SPECS, TAP_COOLDOWN_SECONDS
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.task_runner import BaseTask, TaskRunResult, TaskSceneAnchor, TaskState
from src.vision_matcher import MatchResult, Roi


@dataclass(frozen=True)
class KingdomVaultClickPlan:
    reason: str
    badge_center: tuple[int, int]
    tap_point: tuple[int, int]
    confidence: float = 0.0


@dataclass(frozen=True)
class KingdomVaultSection:
    key: str
    reason: str
    asset_names: tuple[str, ...]
    badge_roi: Roi
    fallback_point: tuple[int, int]


class KingdomVaultTask(BaseTask):
    spec = TASK_SPECS["kingdom_vault"]
    required_assets = (
        "vault_title.png",
        "exclamation_badge.png",
        "event_exclamation_badge.png",
        "play.png",
        "side_battle_pass.png",
        "side_special_offer.png",
        "side_special_offer_alt.png",
    )

    TITLE_ROI: Roi = (60, 0, 180, 65)
    DAILY_FREE_BADGE_ROI: Roi = (430, 200, 45, 35)
    AD_PLAY_ICON_ROI: Roi = (300, 250, 550, 85)
    SIDE_TAB_ROI: Roi = (25, 70, 120, 410)
    SIDE_BATTLE_PASS_FALLBACK_POINT = (80, 100)
    SIDE_SPECIAL_OFFER_FALLBACK_POINT = (82, 399)
    RIGHT_TOP_TAB_BADGE_ROI: Roi = (200, 20, 730, 80)
    SPECIAL_OFFER_TAB_BADGE_ROI: Roi = (200, 35, 580, 60)
    BATTLE_PASS_TAB_BADGE_ROI: Roi = (220, 20, 690, 70)
    BATTLE_PASS_COLLECT_ALL_BADGE_ROI: Roi = (540, 455, 85, 55)
    BATTLE_PASS_REWARD_BADGE_ROI: Roi = (180, 100, 740, 360)
    BATTLE_PASS_RESET_BUTTON_ROI: Roi = (555, 470, 130, 45)
    RESET_CONFIRM_DIALOG_ROI: Roi = (240, 95, 485, 350)
    RESET_CONFIRM_BUTTON_ROI: Roi = (505, 375, 175, 55)
    CLAIM_SETTLE_SECONDS = 2.0
    CLAIM_ANIMATION_POLL_SECONDS = 0.5
    CLAIM_ANIMATION_MAX_POLLS = 12
    AD_START_WAIT_SECONDS = 8.0
    CLAIM_REASONS = {"daily_free", "ad_free", "battle_pass_collect_all", "battle_pass_reward"}
    RESET_REASONS = {"battle_pass_reset", "reset_confirm"}
    TAB_REASONS = {"top_tab", "battle_pass_tab", "special_offer_tab"}
    SECTION_REASONS = {"battle_pass_side_section", "special_offer_side_section"}
    MAX_CLEAR_STEPS = 40
    BADGE_TEMPLATE_THRESHOLD = 0.84
    BADGE_TEMPLATE_NAMES = ("exclamation_badge.png", "event_exclamation_badge.png")
    ENABLE_COLOR_BADGE_FALLBACK = False
    SIDE_MENU_SEARCH_SWIPES = (
        (86, 430, 86, 130),
        (86, 130, 86, 430),
    )

    task_scene_anchors = (
        TaskSceneAnchor("vault_title.png", threshold=0.92, roi=TITLE_ROI),
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
            if require_current_scene and not self.is_current_task_scene():
                raise TaskFailedError(f"Current screen is not the {self.spec.display_name} task scene")
            return self._result(TaskState.COMPLETED, self.execute(), started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except (BotError, TaskFailedError) as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        return self.clear_all_notifications()

    def clear_all_notifications(self, *, max_steps: int = MAX_CLEAR_STEPS) -> str:
        claims = 0
        tabs = 0
        sections = 0
        resets = 0
        side_swipes = 0
        for _ in range(max_steps):
            screen = self.context.controller.screenshot()
            plan = self.plan_next_action(screen)
            if plan is not None:
                self._tap_plan(plan)
                if plan.reason in self.CLAIM_REASONS:
                    claims += 1
                elif plan.reason in self.TAB_REASONS:
                    tabs += 1
                elif plan.reason in self.SECTION_REASONS:
                    sections += 1
                elif plan.reason == "reset_confirm":
                    resets += 1
                side_swipes = 0
                continue

            if side_swipes < len(self.SIDE_MENU_SEARCH_SWIPES):
                self._swipe_side_menu(self.SIDE_MENU_SEARCH_SWIPES[side_swipes])
                side_swipes += 1
                continue

            return f"kingdom vault cleared; claims={claims}; tabs={tabs}; sections={sections}; resets={resets}"
        raise TaskFailedError(f"Kingdom Vault notification clearing exceeded {max_steps} steps")

    def claim_special_offer_tabs(self, *, max_tabs: int = 5) -> int:
        claimed = self.claim_daily_free()
        visited_tab_bins: set[int] = set()
        for _ in range(max_tabs):
            screen = self.context.controller.screenshot()
            tab_plan = self.plan_next_special_offer_tab(screen, visited_tab_bins)
            if tab_plan is None:
                break
            visited_tab_bins.add(tab_plan.badge_center[0] // 40)
            self._tap_plan(tab_plan)
            claimed += self.claim_daily_free()
        self._log(f"Kingdom Vault special-offer claimed={claimed}")
        return claimed

    def claim_daily_free(self) -> int:
        screen = self.context.controller.screenshot()
        plan = self.plan_daily_free_claim(screen)
        if plan is None:
            self._log("Kingdom Vault daily free badge not found; skipped")
            return 0
        self._tap_plan(plan)
        return 1

    def claim_battle_pass_tabs(self, *, max_tabs: int = 8) -> int:
        claimed = self.claim_current_battle_pass_rewards()
        visited_tab_bins: set[int] = set()
        for _ in range(max_tabs):
            screen = self.context.controller.screenshot()
            tab_plan = self.plan_next_battle_pass_tab(screen, visited_tab_bins)
            if tab_plan is None:
                break
            visited_tab_bins.add(tab_plan.badge_center[0] // 40)
            self._tap_plan(tab_plan)
            claimed += self.claim_current_battle_pass_rewards()
        self._log(f"Kingdom Vault battle-pass claimed={claimed}")
        return claimed

    def claim_current_battle_pass_rewards(self, *, max_claims: int = 12) -> int:
        claimed = 0
        for _ in range(max_claims):
            screen = self.context.controller.screenshot()
            plan = self.plan_next_battle_pass_reward_claim(screen)
            if plan is None:
                break
            self._tap_plan(plan)
            claimed += 1
            if plan.reason == "battle_pass_collect_all":
                break
        return claimed

    def plan_daily_free_claim(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        badge = self._best_badge_candidate(screen, self.DAILY_FREE_BADGE_ROI, include_color=True)
        if badge is None:
            return None
        return KingdomVaultClickPlan(
            reason="daily_free",
            badge_center=badge.center,
            tap_point=self._offset_point(badge.center, -10, 12),
            confidence=badge.confidence,
        )

    def plan_current_page_claim(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        plans = [
            self.plan_daily_free_claim(screen),
            self.plan_ad_free_claim(screen),
            self.plan_next_battle_pass_reward_claim(screen),
        ]
        return next((plan for plan in plans if plan is not None), None)

    def plan_ad_free_claim(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        play = self.context.matcher.match_template(
            screen,
            self.asset_path("play.png"),
            threshold=0.88,
            roi=self.AD_PLAY_ICON_ROI,
            check_brightness=False,
        )
        if play is None:
            return None
        return KingdomVaultClickPlan(
            reason="ad_free",
            badge_center=play.center,
            tap_point=self._offset_point(play.center, 36, 0),
            confidence=play.confidence,
        )

    def plan_next_action(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        plans = [
            self.plan_reset_confirm(screen),
            self.plan_current_page_claim(screen),
            self.plan_current_page_reset(screen),
            self.plan_current_page_tab(screen),
            self.plan_next_side_section(screen),
        ]
        return next((plan for plan in plans if plan is not None), None)

    def plan_current_page_tab(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        return self.plan_next_top_tab(screen)

    def plan_current_page_reset(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        match = self._colored_button_candidate(
            screen,
            self.BATTLE_PASS_RESET_BUTTON_ROI,
            kind="red",
            min_ratio=0.18,
        )
        if match is None:
            return None
        return KingdomVaultClickPlan(
            reason="battle_pass_reset",
            badge_center=match.center,
            tap_point=match.center,
            confidence=match.confidence,
        )

    def plan_reset_confirm(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        if not self._is_reset_confirm_dialog_visible(screen):
            return None
        match = self._colored_button_candidate(
            screen,
            self.RESET_CONFIRM_BUTTON_ROI,
            kind="blue",
            min_ratio=0.22,
        )
        if match is None:
            return None
        return KingdomVaultClickPlan(
            reason="reset_confirm",
            badge_center=match.center,
            tap_point=match.center,
            confidence=match.confidence,
        )

    def plan_next_side_section(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        plans = []
        for section in self.sections():
            badge = self._best_badge_candidate(screen, section.badge_roi, include_color=False)
            if badge is None:
                continue
            tap_point = self._side_section_tap_point(screen, section)
            plans.append(
                KingdomVaultClickPlan(
                    reason=section.reason,
                    badge_center=badge.center,
                    tap_point=tap_point,
                    confidence=badge.confidence,
                )
            )
        if not plans:
            return None
        return min(plans, key=lambda plan: plan.badge_center[1])

    def plan_next_battle_pass_tab(
        self,
        screen: np.ndarray,
        visited_tab_bins: Iterable[int] = (),
    ) -> Optional[KingdomVaultClickPlan]:
        return self.plan_next_top_tab(screen, visited_tab_bins, reason="battle_pass_tab", roi=self.BATTLE_PASS_TAB_BADGE_ROI)

    def plan_next_special_offer_tab(
        self,
        screen: np.ndarray,
        visited_tab_bins: Iterable[int] = (),
    ) -> Optional[KingdomVaultClickPlan]:
        return self.plan_next_top_tab(
            screen,
            visited_tab_bins,
            reason="special_offer_tab",
            roi=self.SPECIAL_OFFER_TAB_BADGE_ROI,
        )

    def plan_next_top_tab(
        self,
        screen: np.ndarray,
        visited_tab_bins: Iterable[int] = (),
        *,
        reason: str = "top_tab",
        roi: Roi | None = None,
    ) -> Optional[KingdomVaultClickPlan]:
        visited = set(visited_tab_bins)
        matches = self._badge_candidates(screen, roi or self.RIGHT_TOP_TAB_BADGE_ROI, include_color=False)
        for match in sorted(matches, key=lambda item: item.center[0]):
            if match.center[0] // 40 in visited:
                continue
            return KingdomVaultClickPlan(
                reason=reason,
                badge_center=match.center,
                tap_point=self._clamp_point((match.center[0] - 62, match.center[1] + 18)),
                confidence=match.confidence,
            )
        return None

    def plan_next_battle_pass_reward_claim(self, screen: np.ndarray) -> Optional[KingdomVaultClickPlan]:
        collect_all = self._best_badge_candidate(
            screen,
            self.BATTLE_PASS_COLLECT_ALL_BADGE_ROI,
            include_color=True,
        )
        if collect_all is not None:
            return KingdomVaultClickPlan(
                reason="battle_pass_collect_all",
                badge_center=collect_all.center,
                tap_point=self._offset_point(collect_all.center, -10, 12),
                confidence=collect_all.confidence,
            )

        matches = self._badge_candidates(screen, self.BATTLE_PASS_REWARD_BADGE_ROI, include_color=False)
        for match in sorted(matches, key=lambda item: (item.center[1], item.center[0])):
            if match.center[0] < 190 or match.center[1] < 115:
                continue
            return KingdomVaultClickPlan(
                reason="battle_pass_reward",
                badge_center=match.center,
                tap_point=self._offset_point(match.center, -10, 12),
                confidence=match.confidence,
            )
        return None

    def _best_badge_candidate(
        self,
        screen: np.ndarray,
        roi: Roi,
        *,
        include_color: bool,
    ) -> Optional[MatchResult]:
        candidates = self._badge_candidates(screen, roi, include_color=include_color)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    def _badge_candidates(
        self,
        screen: np.ndarray,
        roi: Roi,
        *,
        include_color: bool,
    ) -> list[MatchResult]:
        template_matches: list[MatchResult] = []
        for template_name in self.BADGE_TEMPLATE_NAMES:
            template_matches.extend(
                self.context.matcher.match_template_all(
                    screen,
                    self.asset_path(template_name),
                    threshold=self.BADGE_TEMPLATE_THRESHOLD,
                    roi=roi,
                    check_brightness=False,
                    max_results=20,
                    min_center_distance=12,
                )
            )
        color_matches = (
            self._red_badge_candidates(screen, roi)
            if include_color and self.ENABLE_COLOR_BADGE_FALLBACK
            else []
        )
        return self._dedupe_matches(template_matches + color_matches)

    def _red_badge_candidates(self, screen: np.ndarray, roi: Roi) -> list[MatchResult]:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return []
        blue, green, red = cv2.split(crop)
        strongest_other = np.maximum(blue, green).astype(np.int16)
        red_i = red.astype(np.int16)
        mask = (
            (red >= 180)
            & (green <= 95)
            & (blue <= 95)
            & ((red_i - strongest_other) >= 90)
        ).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        matches: list[MatchResult] = []
        for contour in contours:
            cx, cy, cw, ch = cv2.boundingRect(contour)
            if not 8 <= cw <= 24 or not 8 <= ch <= 24:
                continue
            area = cw * ch
            fill_ratio = float(np.count_nonzero(mask[cy : cy + ch, cx : cx + cw])) / float(area)
            if fill_ratio < 0.35 or fill_ratio > 0.95:
                continue
            abs_x = x + cx
            abs_y = y + cy
            matches.append(
                MatchResult(
                    template_path=self.asset_path("exclamation_badge.png"),
                    confidence=min(0.90, fill_ratio),
                    center=(abs_x + cw // 2, abs_y + ch // 2),
                    bbox=(abs_x, abs_y, cw, ch),
                )
            )
        return matches

    def _dedupe_matches(self, matches: list[MatchResult]) -> list[MatchResult]:
        kept: list[MatchResult] = []
        for match in sorted(matches, key=lambda item: item.confidence, reverse=True):
            if any(self._distance_sq(match.center, existing.center) < 14 * 14 for existing in kept):
                continue
            kept.append(match)
        return sorted(kept, key=lambda item: (item.center[1], item.center[0]))

    def _is_reset_confirm_dialog_visible(self, screen: np.ndarray) -> bool:
        x, y, w, h = self.RESET_CONFIRM_DIALOG_ROI
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return False
        blue, green, red = cv2.split(crop)
        dark_mask = (blue < 80) & (green < 80) & (red < 80)
        return float(np.count_nonzero(dark_mask)) / float(dark_mask.size) > 0.55

    def _colored_button_candidate(
        self,
        screen: np.ndarray,
        roi: Roi,
        *,
        kind: str,
        min_ratio: float,
    ) -> Optional[MatchResult]:
        x, y, w, h = roi
        crop = screen[y : y + h, x : x + w]
        if crop.size == 0:
            return None
        blue, green, red = cv2.split(crop)
        if kind == "red":
            mask = (red > 145) & (green < 95) & (blue < 120)
        elif kind == "blue":
            mask = (blue > 150) & (green > 110) & (red < 120)
        else:
            raise ValueError(f"Unsupported colored button kind: {kind}")
        mask = mask.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
        ratio = float(np.count_nonzero(mask)) / float(mask.size)
        if ratio < min_ratio:
            return None
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        cx, cy, cw, ch = cv2.boundingRect(contour)
        bbox = (x + cx, y + cy, cw, ch)
        return MatchResult(
            template_path=self.spec.asset_dir / f"{kind}_button_color",
            confidence=min(0.99, ratio),
            center=(x + w // 2, y + h // 2),
            bbox=bbox,
        )

    def _tap_plan(self, plan: KingdomVaultClickPlan) -> None:
        x, y = plan.tap_point
        self.context.controller.annotate_next_tap_debug(
            lines=[
                f"kingdom_vault {plan.reason}",
                f"badge={plan.badge_center} confidence={plan.confidence:.3f}",
            ],
            boxes=[(plan.badge_center[0] - 8, plan.badge_center[1] - 8, 16, 16, "badge")],
        )
        self._log(
            f"Kingdom Vault {plan.reason}: badge={plan.badge_center} "
            f"tap={plan.tap_point} confidence={plan.confidence:.3f}"
        )
        self.context.controller.tap(x, y)
        if plan.reason == "ad_free":
            time.sleep(TAP_COOLDOWN_SECONDS)
            self._run_ads2_for_ad_reward()
        elif plan.reason in self.CLAIM_REASONS:
            time.sleep(self.CLAIM_SETTLE_SECONDS)
            self._wait_for_claim_animation_to_clear()
        else:
            time.sleep(TAP_COOLDOWN_SECONDS)

    def _run_ads2_for_ad_reward(self) -> None:
        serial = getattr(self.context.controller, "serial", None)
        self._log("Kingdom Vault ad_free: running ads2 profile kingdom_vault")
        self._wait_for_ad_to_leave_vault()
        runner = ReactiveRunner(
            serial=serial,
            ad_wait=15,
            debug=self.context.logger.enabled if self.context.logger is not None else False,
            profile="kingdom_vault",
        )
        runner.run()

    def _wait_for_ad_to_leave_vault(self) -> None:
        deadline = time.time() + self.AD_START_WAIT_SECONDS
        while time.time() < deadline:
            screen = self.context.controller.screenshot()
            if not self.is_task_scene(screen):
                return
            time.sleep(0.5)
        self._log("Kingdom Vault ad_free: vault title still visible before ads2 start")

    def _wait_for_claim_animation_to_clear(self) -> None:
        clear_polls = 0
        for _ in range(self.CLAIM_ANIMATION_MAX_POLLS):
            screen = self.context.controller.screenshot()
            blocker = getattr(self.context, "blocker", None)
            if blocker is not None and blocker.handle_known_blocker(screen):
                clear_polls = 0
                continue
            if self._is_claim_animation_visible(screen):
                clear_polls = 0
            else:
                clear_polls += 1
            if clear_polls >= 2:
                return
            time.sleep(self.CLAIM_ANIMATION_POLL_SECONDS)

    @staticmethod
    def _is_claim_animation_visible(screen: np.ndarray) -> bool:
        if screen.size == 0:
            return False
        crop = screen[120:220, 330:650]
        if crop.size == 0:
            return False
        blue, green, red = cv2.split(crop)
        cyan_mask = (blue > 150) & (green > 110) & (red < 130)
        return float(np.count_nonzero(cyan_mask)) / float(cyan_mask.size) > 0.05

    def _open_battle_pass_side_tab(self) -> None:
        self._tap_side_tab(
            "battle_pass_side_tab",
            ("side_battle_pass.png",),
            fallback_point=self.SIDE_BATTLE_PASS_FALLBACK_POINT,
        )

    def _open_special_offer_side_tab(self) -> None:
        self._tap_side_tab(
            "special_offer_side_tab",
            ("side_special_offer.png", "side_special_offer_alt.png"),
            fallback_point=self.SIDE_SPECIAL_OFFER_FALLBACK_POINT,
        )

    @classmethod
    def sections(cls) -> tuple[KingdomVaultSection, ...]:
        return (
            KingdomVaultSection(
                key="battle_pass",
                reason="battle_pass_side_section",
                asset_names=("side_battle_pass.png",),
                badge_roi=(150, 70, 40, 55),
                fallback_point=cls.SIDE_BATTLE_PASS_FALLBACK_POINT,
            ),
            KingdomVaultSection(
                key="special_offer",
                reason="special_offer_side_section",
                asset_names=("side_special_offer.png", "side_special_offer_alt.png"),
                badge_roi=(150, 365, 40, 55),
                fallback_point=cls.SIDE_SPECIAL_OFFER_FALLBACK_POINT,
            ),
        )

    def _side_section_tap_point(self, screen: np.ndarray, section: KingdomVaultSection) -> tuple[int, int]:
        best: Optional[MatchResult] = None
        for asset_name in section.asset_names:
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=0.82,
                roi=self.SIDE_TAB_ROI,
                check_brightness=False,
            )
            if match is None:
                continue
            if best is None or match.confidence > best.confidence:
                best = match
        return best.center if best is not None else section.fallback_point

    def _tap_side_tab(
        self,
        reason: str,
        asset_names: tuple[str, ...],
        *,
        fallback_point: tuple[int, int],
    ) -> None:
        screen = self.context.controller.screenshot()
        best: Optional[MatchResult] = None
        for asset_name in asset_names:
            match = self.context.matcher.match_template(
                screen,
                self.asset_path(asset_name),
                threshold=0.82,
                roi=self.SIDE_TAB_ROI,
                check_brightness=False,
            )
            if match is None:
                continue
            if best is None or match.confidence > best.confidence:
                best = match
        tap_point = best.center if best is not None else fallback_point
        self._log(
            f"Kingdom Vault open {reason}: tap={tap_point} "
            f"confidence={(best.confidence if best else 0.0):.3f}"
        )
        self.context.controller.annotate_next_tap_debug(
            lines=[
                f"kingdom_vault {reason}",
                f"confidence={(best.confidence if best else 0.0):.3f}",
            ],
            boxes=[best.bbox + ("side_tab",)] if best is not None else [],
        )
        self.context.controller.tap(*tap_point)
        time.sleep(TAP_COOLDOWN_SECONDS)

    def _swipe_side_menu(self, points: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = points
        self._log(f"Kingdom Vault side menu search swipe: ({x1},{y1}) -> ({x2},{y2})")
        self.context.controller.swipe(x1, y1, x2, y2, duration_ms=420)
        time.sleep(TAP_COOLDOWN_SECONDS)

    @staticmethod
    def _distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    def _offset_point(self, point: tuple[int, int], dx: int, dy: int) -> tuple[int, int]:
        return self._clamp_point((point[0] + dx, point[1] + dy))

    @staticmethod
    def _clamp_point(point: tuple[int, int]) -> tuple[int, int]:
        width, height = EXPECTED_SCREEN_SIZE
        x = max(0, min(width - 1, int(point[0])))
        y = max(0, min(height - 1, int(point[1])))
        return x, y
