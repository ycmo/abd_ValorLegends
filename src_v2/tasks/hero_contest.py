from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.config import TASK_SPECS, TAP_COOLDOWN_SECONDS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.vision_matcher import MatchResult, Roi


@dataclass(frozen=True)
class HeroContestResult:
    kind: str
    match: MatchResult


class HeroContestTask(BaseTask):
    spec = TASK_SPECS["hero_contest"]
    required_assets = (
        "challenge_button.png",
        "battle_challenge_button.png",
        "skip_button.png",
        "victory_continue_button.png",
        "defeat_continue_button.png",
        "refresh_button.png",
        "attempts_zero_anchor.png",
        "hero_tab_anchor.png",
    )

    MAIN_CHALLENGE_ROI: Roi = (470, 430, 220, 75)
    REFRESH_ROI: Roi = (500, 350, 170, 65)
    HERO_TAB_ROI: Roi = (0, 80, 190, 80)
    TEAM_CHALLENGE_ROI: Roi = (825, 430, 130, 105)
    SKIP_ROI: Roi = (885, 75, 65, 70)
    VICTORY_CONTINUE_ROI: Roi = (420, 450, 130, 70)
    DEFEAT_CONTINUE_ROI: Roi = (420, 485, 140, 45)
    ATTEMPTS_ZERO_ROI: Roi = (600, 480, 70, 40)
    ATTEMPTS_ZERO_THRESHOLD = 0.86

    TARGET_REWARD_WINS = 4
    MAX_BATTLES = 8
    MAX_CONSECUTIVE_LOSSES_BEFORE_REFRESH = 2
    RESULT_TIMEOUT_SECONDS = 150.0
    RESULT_CONTINUE_MAX_TAPS = 3

    task_scene_anchors = (
        TaskSceneAnchor("hero_tab_anchor.png", threshold=0.86, roi=HERO_TAB_ROI),
        TaskSceneAnchor("refresh_button.png", threshold=0.86, roi=REFRESH_ROI),
        TaskSceneAnchor("challenge_button.png", threshold=0.86, roi=MAIN_CHALLENGE_ROI),
        TaskSceneAnchor("battle_challenge_button.png", threshold=0.86, roi=TEAM_CHALLENGE_ROI),
        TaskSceneAnchor("skip_button.png", threshold=0.84, roi=SKIP_ROI),
        TaskSceneAnchor("victory_continue_button.png", threshold=0.84, roi=VICTORY_CONTINUE_ROI),
        TaskSceneAnchor("defeat_continue_button.png", threshold=0.84, roi=DEFEAT_CONTINUE_ROI),
    )

    def execute(self) -> str:
        fights = 0
        wins = 0
        losses = 0
        refreshes = 0
        consecutive_losses = 0
        route_recovers = 0

        while wins < self.TARGET_REWARD_WINS and fights < self.MAX_BATTLES:
            if self._attempts_exhausted():
                self._log(f"Hero contest attempts exhausted before fight; fights={fights}")
                return "hero contest attempts exhausted"

            fight_index = fights + 1
            self._log(
                "Hero contest fight "
                f"{fight_index}; wins={wins}/{self.TARGET_REWARD_WINS}; "
                f"consecutive_losses={consecutive_losses}"
            )

            self._tap(
                "hero contest main challenge",
                "challenge_button.png",
                roi=self.MAIN_CHALLENGE_ROI,
                threshold=0.86,
                timeout_seconds=8.0,
                wait_after=TRANSITION_WAIT_SECONDS,
            )
            self._tap(
                "hero contest team challenge",
                "battle_challenge_button.png",
                roi=self.TEAM_CHALLENGE_ROI,
                threshold=0.86,
                timeout_seconds=8.0,
                wait_after=TRANSITION_WAIT_SECONDS,
            )
            self._tap(
                "hero contest skip battle",
                "skip_button.png",
                roi=self.SKIP_ROI,
                threshold=0.84,
                timeout_seconds=30.0,
                wait_after=TRANSITION_WAIT_SECONDS,
            )

            result = self._wait_for_result()
            self._dismiss_result(result)
            if not self._recover_to_main_screen_after_result():
                raise TaskFailedError("Hero contest could not recover to main screen after battle result")
            route_recovers += 1

            fights += 1
            if result.kind == "win":
                wins += 1
                consecutive_losses = 0
            else:
                losses += 1
                consecutive_losses += 1
            self._log(
                f"Hero contest result={result.kind}; fights={fights}; "
                f"wins={wins}; losses={losses}; consecutive_losses={consecutive_losses}"
            )

            if wins < self.TARGET_REWARD_WINS and consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES_BEFORE_REFRESH:
                self._tap(
                    "hero contest refresh after consecutive losses",
                    "refresh_button.png",
                    roi=self.REFRESH_ROI,
                    threshold=0.86,
                    timeout_seconds=8.0,
                    wait_after=TRANSITION_WAIT_SECONDS,
                )
                refreshes += 1
                consecutive_losses = 0
                self._log(f"Hero contest refreshed opponent; refreshes={refreshes}")

        return (
            f"hero contest fights={fights}; wins={wins}; losses={losses}; "
            f"refreshes={refreshes}; route_recovers={route_recovers}"
        )

    def _wait_for_result(self) -> HeroContestResult:
        # Retained custom loop because it waits for multiple conditions (victory or defeat button)
        deadline = time.time() + self.RESULT_TIMEOUT_SECONDS
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            victory = self._match_asset_on_screen(
                screen,
                "victory_continue_button.png",
                roi=self.VICTORY_CONTINUE_ROI,
                threshold=0.84,
            )
            if victory is not None:
                return HeroContestResult("win", victory)

            defeat = self._match_asset_on_screen(
                screen,
                "defeat_continue_button.png",
                roi=self.DEFEAT_CONTINUE_ROI,
                threshold=0.84,
            )
            if defeat is not None:
                return HeroContestResult("loss", defeat)

            time.sleep(2.0)
        raise TaskFailedError("Hero contest timed out waiting for victory/defeat continue button")

    def _require_main_screen(self) -> MatchResult:
        # Retained custom loop because it waits for multiple screen elements (hero tab, challenge button, or refresh)
        deadline = time.time() + 12.0
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self._find_main_screen_on_screen(screen)
            if match is not None:
                return match
            time.sleep(0.5)
        raise TaskFailedError("Hero contest expected screen element not found: hero contest main screen")

    def _attempts_exhausted(self) -> bool:
        screen = self.context.controller.screenshot()
        path = self._asset_path("attempts_zero_anchor.png")
        best = self.context.matcher.best_template_match(screen, path, roi=self.ATTEMPTS_ZERO_ROI)
        confidence = 0.0 if best is None else best.confidence
        exhausted = confidence >= self.ATTEMPTS_ZERO_THRESHOLD
        boxes = [(*self.ATTEMPTS_ZERO_ROI, "roi")]
        if best is not None:
            boxes.append((*best.bbox, "go" if exhausted else "status_roi"))
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is not None:
            save_debug(
                "hero_contest_attempts_zero_probe",
                screen,
                lines=[
                    "Hero contest attempts zero probe",
                    f"roi={self.ATTEMPTS_ZERO_ROI}",
                    f"confidence={confidence:.4f} threshold={self.ATTEMPTS_ZERO_THRESHOLD:.4f}",
                    f"exhausted={exhausted}",
                ],
                boxes=boxes,
                panel_position="right",
            )
        self._log(
            "Hero contest attempts zero probe "
            f"roi={self.ATTEMPTS_ZERO_ROI} confidence={confidence:.4f} "
            f"threshold={self.ATTEMPTS_ZERO_THRESHOLD:.4f} exhausted={exhausted}"
        )
        return exhausted

    def _dismiss_result(self, result: HeroContestResult) -> None:
        # Retained custom loop because it requires checking for multiple target states (main screen or result)
        taps = 0
        deadline = time.time() + 15.0
        current_result: Optional[HeroContestResult] = result
        while time.time() <= deadline:
            if current_result is not None:
                taps += 1
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        f"hero contest {current_result.kind} continue {taps}/{self.RESULT_CONTINUE_MAX_TAPS}",
                        f"{current_result.match.template_path.name} confidence={current_result.match.confidence:.3f}",
                    ],
                    boxes=[(*current_result.match.bbox, "go")],
                )
                self.context.controller.tap(*current_result.match.center)
                time.sleep(1.0)
                if taps >= self.RESULT_CONTINUE_MAX_TAPS:
                    self._save_result_still_visible_debug(current_result)
                    raise TaskFailedError(
                        "Hero contest result continue did not leave result screen after confirmed retries"
                    )

            screen = self.context.controller.screenshot()
            if self._find_main_screen_on_screen(screen) is not None:
                return

            current_result = self._find_result_on_screen(screen)
            if current_result is not None:
                self._log(
                    "Hero contest result still visible after continue; "
                    f"retrying with fresh match confidence={current_result.match.confidence:.3f}"
                )
                continue

            self._log("Hero contest result continue reached non-result screen")
            return

            time.sleep(0.5)

        raise TaskFailedError("Hero contest result continue landed on an unrecognized screen")

    def _recover_to_main_screen_after_result(self) -> bool:
        if self._is_main_screen_visible():
            return True

        self._log("Hero contest main screen not visible after result; recovering through navigator")
        # TODO: cut-over 後恢復 AFK route，這裡先改用 navigator.recover_to_main()
        if hasattr(self.context, 'navigator') and hasattr(self.context.navigator, 'recover_to_main'):
            self.context.navigator.recover_to_main()
        return self._is_main_screen_visible(timeout_seconds=8.0)

    def _is_main_screen_visible(self, timeout_seconds: float = 0.8) -> bool:
        # Retained custom loop because it requires checking for multiple anchor elements
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._find_main_screen_on_screen(screen) is not None:
                return True
            time.sleep(0.25)
        return False

    def _save_result_still_visible_debug(self, result: HeroContestResult) -> None:
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is None:
            return
        screen = self.context.controller.screenshot()
        save_debug(
            "hero_contest_result_continue_still_visible",
            screen,
            lines=[
                "Hero contest result still visible after one continue tap",
                f"result={result.kind}",
                f"{result.match.template_path.name} confidence={result.match.confidence:.3f}",
                "max confirmed retries reached",
            ],
            boxes=[(*result.match.bbox, "status_roi")],
            panel_position="right",
        )

    def _find_main_screen_on_screen(self, screen) -> Optional[MatchResult]:
        tab = self._match_asset_on_screen(
            screen,
            "hero_tab_anchor.png",
            roi=self.HERO_TAB_ROI,
            threshold=0.86,
        )
        if tab is None:
            return None

        challenge = self._match_asset_on_screen(
            screen,
            "challenge_button.png",
            roi=self.MAIN_CHALLENGE_ROI,
            threshold=0.86,
        )
        if challenge is not None:
            return challenge
        return self._match_asset_on_screen(
            screen,
            "refresh_button.png",
            roi=self.REFRESH_ROI,
            threshold=0.86,
        )

    def _find_result_on_screen(self, screen) -> Optional[HeroContestResult]:
        victory = self._match_asset_on_screen(
            screen,
            "victory_continue_button.png",
            roi=self.VICTORY_CONTINUE_ROI,
            threshold=0.84,
        )
        if victory is not None:
            return HeroContestResult("win", victory)
        defeat = self._match_asset_on_screen(
            screen,
            "defeat_continue_button.png",
            roi=self.DEFEAT_CONTINUE_ROI,
            threshold=0.84,
        )
        if defeat is not None:
            return HeroContestResult("loss", defeat)
        return None

    def _match_asset_on_screen(
        self,
        screen,
        asset_name: str,
        *,
        roi: Roi,
        threshold: float,
    ) -> Optional[MatchResult]:
        return self.context.matcher.match_template(
            screen,
            self._asset_path(asset_name),
            threshold=threshold,
            roi=roi,
        )
