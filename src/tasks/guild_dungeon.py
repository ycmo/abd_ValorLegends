from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import CAPTURES_DIR, SHARED_ASSETS_DIR, TASK_ASSETS_DIR, TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult


@dataclass(frozen=True)
class GuildDungeonTarget:
    kind: str
    match: MatchResult


@dataclass(frozen=True)
class GuildDungeonProbeRecord:
    scan_index: int
    node_kind: str
    node_center: tuple[int, int]
    node_confidence: float
    remaining_count: int
    challenge_count: int
    bonus_count: int
    selected_center: Optional[tuple[int, int]]
    selected_confidence: float


class GuildDungeonTask(BaseTask):
    spec = TASK_SPECS["guild_dungeon"]
    required_assets = (
        "task_label.png",
        "map_title_anchor.png",
        "sword_node_anchor.png",
        "flag_node_anchor.png",
        "remaining_attempt_anchor.png",
        "bonus_reward_anchor.png",
        "bonus_reward_anchor_alt.png",
        "challenge_button.png",
        "continue_button.png",
        "outpost_close_button.png",
        "back_button.png",
        "remaining_attempts_zero_anchor.png",
    )
    task_scene_anchors = (
        TaskSceneAnchor("map_title_anchor.png", threshold=0.86, roi=(0, 0, 260, 110)),
        TaskSceneAnchor("sword_node_anchor.png", threshold=0.80),
        TaskSceneAnchor("flag_node_anchor.png", threshold=0.86),
    )

    MAP_SWIPES = ((820, 270, 220, 270, 650),)
    TARGET_BATTLES = 2
    MAX_FLOW_FAILURES = 3
    OUTPOST_WAIT_SECONDS = TRANSITION_WAIT_SECONDS
    MAP_NODE_THRESHOLD = 0.80
    FLAG_NODE_THRESHOLD = 0.86
    REMAINING_ATTEMPT_THRESHOLD = 0.78
    CHALLENGE_BUTTON_THRESHOLD = 0.82
    BONUS_REWARD_THRESHOLD = 0.75
    CONTINUE_BUTTON_THRESHOLD = 0.82
    CLOSE_BUTTON_THRESHOLD = 0.76
    BATTLE_READY_THRESHOLD = 0.82
    REMAINING_DAILY_ZERO_THRESHOLD = 0.86

    REMAINING_ROI = (120, 350, 560, 45)
    CHALLENGE_ROI = (90, 290, 620, 90)
    BONUS_ROI = (250, 110, 470, 110)
    CONTINUE_ROI = (390, 430, 190, 90)
    CLOSE_ROI = (760, 10, 130, 90)
    REMAINING_DAILY_ZERO_ROI = (105, 78, 45, 35)
    START_BATTLE_POINT = (902, 480)
    BATTLE_READY_ASSET = TASK_ASSETS_DIR / "endless_trial" / "battle_ready_anchor.png"

    def __init__(self, context):
        super().__init__(context)
        self.last_probe_records: list[GuildDungeonProbeRecord] = []
        self.last_probe_summary_path = None

    def missing_assets(self) -> tuple[Path, ...]:
        missing = list(super().missing_assets())
        if not self.BATTLE_READY_ASSET.exists():
            missing.append(self.BATTLE_READY_ASSET)
        return tuple(missing)

    def execute(self) -> str:
        completed = 0
        failures = 0
        battle_messages: list[str] = []
        while completed < self.TARGET_BATTLES:
            try:
                if completed > 0:
                    self._wait_for_map_screen("before next guild dungeon target")
                    screen = self.context.controller.screenshot()
                    if self._close_outpost_if_visible(screen):
                        time.sleep(TRANSITION_WAIT_SECONDS)
                        screen = self.context.controller.screenshot()
                else:
                    screen = self.context.controller.screenshot()
                if self._is_plain_map_screen(screen) and self._daily_attempts_exhausted(screen):
                    battle_messages.append("daily remaining attempts exhausted")
                    break
                if self._match_battle_ready_on_screen(screen) is not None or self._is_battle_ready_screen(timeout_seconds=1.0):
                    target_message = "guild dungeon continued from battle ready"
                else:
                    target_message = self._select_challenge_from_open_outpost(tap_challenge=True)
                    if target_message is None:
                        target_message = self.probe_target_from_current_map(tap_challenge=True)
                self._start_battle_from_ready_screen()
                self._wait_for_battle_continue()
                completed += 1
                failures = 0
                battle_messages.append(f"battle{completed}: {target_message}")
            except TaskFailedError as exc:
                failures += 1
                if failures >= self.MAX_FLOW_FAILURES:
                    raise TaskFailedError(
                        f"Guild dungeon failed {failures} time(s) while trying to complete "
                        f"{self.TARGET_BATTLES} battles; completed={completed}; last_error={exc}"
                    ) from exc
                time.sleep(TRANSITION_WAIT_SECONDS)

        if not self._return_to_daily_tasks():
            raise TaskFailedError("Guild dungeon completed, but could not return to Daily Tasks safely")
        return f"guild dungeon battles completed={completed}; " + "; ".join(battle_messages)

    def _daily_attempts_exhausted(self, screen) -> bool:
        best_match = self.context.matcher.match_template(
            screen,
            self.asset_path("remaining_attempts_zero_anchor.png"),
            threshold=0.0,
            roi=self.REMAINING_DAILY_ZERO_ROI,
            check_brightness=False,
        )
        self._save_daily_attempts_zero_debug(screen, best_match)
        confidence = best_match.confidence if best_match is not None else 0.0
        exhausted = confidence >= self.REMAINING_DAILY_ZERO_THRESHOLD
        self._log(
            "Guild dungeon daily attempts zero probe "
            f"roi={self.REMAINING_DAILY_ZERO_ROI} "
            f"confidence={confidence:.4f} "
            f"threshold={self.REMAINING_DAILY_ZERO_THRESHOLD:.4f} "
            f"exhausted={exhausted}"
        )
        return exhausted

    def _is_plain_map_screen(self, screen) -> bool:
        if self._match_map_title_on_screen(screen) is None:
            return False
        return self.context.matcher.match_template(
            screen,
            self.asset_path("outpost_close_button.png"),
            threshold=self.CLOSE_BUTTON_THRESHOLD,
            roi=self.CLOSE_ROI,
        ) is None

    def _save_daily_attempts_zero_debug(self, screen, best_match: Optional[MatchResult]) -> None:
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is None:
            return
        x, y, w, h = self.REMAINING_DAILY_ZERO_ROI
        confidence = best_match.confidence if best_match is not None else 0.0
        boxes = [(x, y, w, h, "roi")]
        if best_match is not None:
            boxes.append((*best_match.bbox, "label"))
        save_debug(
            "guild_dungeon_daily_attempts_zero_probe",
            screen,
            lines=[
                "guild dungeon daily attempts zero probe",
                f"roi={self.REMAINING_DAILY_ZERO_ROI}",
                f"confidence={confidence:.4f} threshold={self.REMAINING_DAILY_ZERO_THRESHOLD:.4f}",
                f"exhausted={confidence >= self.REMAINING_DAILY_ZERO_THRESHOLD}",
            ],
            boxes=boxes,
            panel_position="right",
        )

    def _log(self, message: str) -> None:
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.log(message)

    def is_task_scene(self, screen) -> bool:
        if super().is_task_scene(screen):
            return True
        return self._match_battle_ready_on_screen(screen) is not None

    def _wait_for_map_screen(self, label: str, timeout_seconds: float = 30.0) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._match_map_title_on_screen(screen) is not None or self._match_outpost_close_on_screen(screen) is not None:
                return
            time.sleep(0.5)
        raise TaskFailedError(f"Guild dungeon map or outpost not visible {label}")

    def _match_map_title_on_screen(self, screen) -> Optional[MatchResult]:
        return self.context.matcher.match_template(
            screen,
            self.asset_path("map_title_anchor.png"),
            threshold=0.86,
            roi=(0, 0, 260, 110),
        )

    def _match_outpost_close_on_screen(self, screen) -> Optional[MatchResult]:
        return self.context.matcher.match_template(
            screen,
            self.asset_path("outpost_close_button.png"),
            threshold=self.CLOSE_BUTTON_THRESHOLD,
            roi=self.CLOSE_ROI,
        )

    def probe_target_from_current_map(self, *, tap_challenge: bool = True) -> str:
        debug_dir = CAPTURES_DIR / "action_debug" / f"guild_dungeon_probe_{time.strftime('%Y%m%d_%H%M%S')}"
        self.last_probe_records = []
        self.last_probe_summary_path = None
        tried_targets: list[tuple[int, int]] = []
        saved_summary = False
        try:
            for scan_index in range(len(self.MAP_SWIPES) + 1):
                screen = self.context.controller.screenshot()
                targets = [
                    target for target in self._find_map_targets(screen)
                    if target.match.center not in tried_targets
                ]
                if not targets:
                    if scan_index < len(self.MAP_SWIPES):
                        self._swipe_map(scan_index)
                        continue
                    raise TaskFailedError("Guild dungeon map target not found")

                for target in targets:
                    tried_targets.append(target.match.center)
                    self._tap_map_target(target)
                    time.sleep(self.OUTPOST_WAIT_SECONDS)

                    outpost_screen = self.context.controller.screenshot()
                    challenge, remaining_matches, challenge_matches = self._find_challenge_probe(outpost_screen)
                    self.last_probe_records.append(
                        GuildDungeonProbeRecord(
                            scan_index=scan_index + 1,
                            node_kind=target.kind,
                            node_center=target.match.center,
                            node_confidence=target.match.confidence,
                            remaining_count=len(remaining_matches),
                            challenge_count=len(challenge_matches),
                            bonus_count=len(self._find_bonus_matches(outpost_screen)),
                            selected_center=challenge.center if challenge is not None else None,
                            selected_confidence=challenge.confidence if challenge is not None else 0.0,
                        )
                    )
                    if challenge is not None:
                        self._save_probe_summary(debug_dir)
                        saved_summary = True
                        self._tap_challenge(challenge, tap_challenge=tap_challenge)
                        return (
                            f"guild dungeon target selected: node={target.kind} "
                            f"node_confidence={target.match.confidence:.3f} "
                            f"challenge_confidence={challenge.confidence:.3f}"
                        )

                    self._close_outpost_if_possible(outpost_screen)
                    time.sleep(self.OUTPOST_WAIT_SECONDS)

                if scan_index < len(self.MAP_SWIPES):
                    self._swipe_map(scan_index)

            raise TaskFailedError("Guild dungeon challenge with remaining attempts not found")
        finally:
            if not saved_summary:
                self._save_probe_summary(debug_dir)

    def _select_challenge_from_open_outpost(self, *, tap_challenge: bool) -> Optional[str]:
        screen = self.context.controller.screenshot()
        challenge, remaining_matches, challenge_matches = self._find_challenge_probe(screen)
        if challenge is None:
            return None
        self._tap_challenge(challenge, tap_challenge=tap_challenge)
        return (
            "guild dungeon challenge selected from open outpost: "
            f"remaining={len(remaining_matches)} challenge={len(challenge_matches)} "
            f"bonus={len(self._find_bonus_matches(screen))} "
            f"challenge_confidence={challenge.confidence:.3f}"
        )

    def _find_map_targets(self, screen) -> list[GuildDungeonTarget]:
        sword_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("sword_node_anchor.png"),
            threshold=self.MAP_NODE_THRESHOLD,
            min_center_distance=60,
        )
        flag_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("flag_node_anchor.png"),
            threshold=self.FLAG_NODE_THRESHOLD,
            min_center_distance=60,
        )
        sword_targets = [
            GuildDungeonTarget("sword", match)
            for match in sorted(sword_matches, key=lambda item: (item.y, item.x))
        ]
        flag_targets = [
            GuildDungeonTarget("flag", match)
            for match in sorted(flag_matches, key=lambda item: (item.y, item.x))
        ]
        return sword_targets + flag_targets

    def _find_challenge_for_remaining_attempt(self, screen) -> Optional[MatchResult]:
        selected, _, _ = self._find_challenge_probe(screen)
        return selected

    def _find_challenge_probe(
        self,
        screen,
    ) -> tuple[Optional[MatchResult], list[MatchResult], list[MatchResult]]:
        remaining_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("remaining_attempt_anchor.png"),
            threshold=self.REMAINING_ATTEMPT_THRESHOLD,
            roi=self.REMAINING_ROI,
            min_center_distance=90,
        )
        challenge_matches = self.context.matcher.match_template_all(
            screen,
            self.asset_path("challenge_button.png"),
            threshold=self.CHALLENGE_BUTTON_THRESHOLD,
            roi=self.CHALLENGE_ROI,
            min_center_distance=120,
        )
        bonus_matches = self._find_bonus_matches(screen)
        if not remaining_matches or not challenge_matches:
            self._save_outpost_probe_debug(screen, remaining_matches, challenge_matches, None)
            return None, remaining_matches, challenge_matches

        remaining_matches = sorted(remaining_matches, key=lambda item: item.x)
        bonus_columns = sorted(match.x for match in bonus_matches)
        if bonus_columns:
            selected = self._select_challenge_from_columns(challenge_matches, remaining_matches, bonus_columns)
            if selected is not None:
                self._save_outpost_probe_debug(screen, remaining_matches, challenge_matches, selected)
                return selected, remaining_matches, challenge_matches

        for remaining in remaining_matches:
            candidates = [
                challenge for challenge in challenge_matches
                if challenge.y < remaining.y and abs(challenge.x - remaining.x) <= 90
            ]
            if not candidates:
                continue
            selected = min(candidates, key=lambda challenge: abs(challenge.x - remaining.x))
            self._save_outpost_probe_debug(screen, remaining_matches, challenge_matches, selected)
            return selected, remaining_matches, challenge_matches

        self._save_outpost_probe_debug(screen, remaining_matches, challenge_matches, None)
        return None, remaining_matches, challenge_matches

    def _find_bonus_matches(self, screen) -> list[MatchResult]:
        matches: list[MatchResult] = []
        for asset_name in ("bonus_reward_anchor.png", "bonus_reward_anchor_alt.png"):
            matches.extend(
                self.context.matcher.match_template_all(
                    screen,
                    self.asset_path(asset_name),
                    threshold=self.BONUS_REWARD_THRESHOLD,
                    roi=self.BONUS_ROI,
                    min_center_distance=70,
                )
            )
        deduped: list[MatchResult] = []
        for match in sorted(matches, key=lambda item: item.x):
            if any(abs(match.x - existing.x) <= 70 for existing in deduped):
                continue
            deduped.append(match)
        return deduped

    def _select_challenge_from_columns(
        self,
        challenge_matches: list[MatchResult],
        remaining_matches: list[MatchResult],
        preferred_columns: list[int],
    ) -> Optional[MatchResult]:
        for column_x in preferred_columns:
            remaining_candidates = [
                remaining for remaining in remaining_matches
                if abs(remaining.x - column_x) <= 90
            ]
            if not remaining_candidates:
                continue
            remaining = min(remaining_candidates, key=lambda item: abs(item.x - column_x))
            challenge_candidates = [
                challenge for challenge in challenge_matches
                if challenge.y < remaining.y and abs(challenge.x - remaining.x) <= 90
            ]
            if challenge_candidates:
                return min(challenge_candidates, key=lambda challenge: abs(challenge.x - remaining.x))
        return None

    def _tap_map_target(self, target: GuildDungeonTarget) -> None:
        self.context.controller.annotate_next_tap_debug(
            lines=[
                f"guild dungeon map target={target.kind}",
                f"confidence={target.match.confidence:.3f}",
            ],
            boxes=[(*target.match.bbox, "go")],
        )
        self.context.controller.tap(*target.match.center)

    def _tap_challenge(self, challenge: MatchResult, *, tap_challenge: bool) -> None:
        if not tap_challenge:
            return
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "guild dungeon selected challenge",
                f"confidence={challenge.confidence:.3f}",
            ],
            boxes=[(*challenge.bbox, "go")],
        )
        self.context.controller.tap(*challenge.center)

    def _start_battle_from_ready_screen(self) -> None:
        deadline = time.time() + 20.0
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self._match_battle_ready_on_screen(screen)
            if match is not None:
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        "guild dungeon battle ready",
                        f"confidence={match.confidence:.3f}",
                    ],
                    boxes=[(*match.bbox, "label")],
                )
                self.context.controller.tap(*self.START_BATTLE_POINT)
                time.sleep(TRANSITION_WAIT_SECONDS)
                return
            time.sleep(1.0)
        raise TaskFailedError("Guild dungeon battle ready screen not found after selecting challenge")

    def _is_battle_ready_screen(self, timeout_seconds: float = 3.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            if self._match_battle_ready_on_screen(screen) is not None:
                return True
            time.sleep(0.35)
        return False

    def _match_battle_ready_on_screen(self, screen) -> Optional[MatchResult]:
        if not self.BATTLE_READY_ASSET.exists():
            return None
        return self.context.matcher.match_template(
            screen,
            self.BATTLE_READY_ASSET,
            threshold=self.BATTLE_READY_THRESHOLD,
        )

    def _wait_for_battle_continue(self) -> None:
        deadline = time.time() + 150.0
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(
                screen,
                self.asset_path("continue_button.png"),
                threshold=self.CONTINUE_BUTTON_THRESHOLD,
                roi=self.CONTINUE_ROI,
            )
            if match is not None:
                self.context.controller.annotate_next_tap_debug(
                    lines=[
                        "guild dungeon battle result continue",
                        f"confidence={match.confidence:.3f}",
                    ],
                    boxes=[(*match.bbox, "go")],
                )
                self.context.controller.tap(*match.center)
                time.sleep(TRANSITION_WAIT_SECONDS)
                return
            time.sleep(2.0)
        raise TaskFailedError("Guild dungeon timed out waiting for battle continue button")

    def _close_outpost_if_possible(self, screen) -> None:
        close_match = self.context.matcher.match_template(
            screen,
            self.asset_path("outpost_close_button.png"),
            threshold=self.CLOSE_BUTTON_THRESHOLD,
            roi=self.CLOSE_ROI,
        )
        if close_match is None:
            self.context.controller.tap(830, 48)
            return
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "guild dungeon outpost has no remaining attempts",
                f"close_confidence={close_match.confidence:.3f}",
            ],
            boxes=[(*close_match.bbox, "go")],
        )
        self.context.controller.tap(*close_match.center)

    def _close_outpost_if_visible(self, screen) -> bool:
        close_match = self._match_outpost_close_on_screen(screen)
        if close_match is None:
            return False
        self.context.controller.annotate_next_tap_debug(
            lines=[
                "guild dungeon close outpost before next battle",
                f"close_confidence={close_match.confidence:.3f}",
            ],
            boxes=[(*close_match.bbox, "go")],
        )
        self.context.controller.tap(*close_match.center)
        return True

    def _return_to_daily_tasks(self) -> bool:
        screen = self.context.controller.screenshot()
        close_match = self.context.matcher.match_template(
            screen,
            self.asset_path("outpost_close_button.png"),
            threshold=self.CLOSE_BUTTON_THRESHOLD,
            roi=self.CLOSE_ROI,
        )
        if close_match is not None:
            self.context.controller.annotate_next_tap_debug(
                lines=[
                    "guild dungeon close outpost before return",
                    f"close_confidence={close_match.confidence:.3f}",
                ],
                boxes=[(*close_match.bbox, "go")],
            )
            self.context.controller.tap(*close_match.center)
            time.sleep(TRANSITION_WAIT_SECONDS)

        returned = self.context.navigator.return_to_daily_tasks_from_known_route(
            max_back_taps=4,
            back_asset=self.asset_path("back_button.png"),
        )
        if returned:
            return True
        return self.context.navigator.return_to_daily_tasks_from_known_route(
            max_back_taps=4,
            back_asset=SHARED_ASSETS_DIR / "back_button2.png",
        )

    def _swipe_map(self, scan_index: int) -> None:
        x1, y1, x2, y2, duration = self.MAP_SWIPES[scan_index]
        self.context.controller.swipe(x1, y1, x2, y2, duration_ms=duration)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def _save_outpost_probe_debug(
        self,
        screen,
        remaining_matches: list[MatchResult],
        challenge_matches: list[MatchResult],
        selected: Optional[MatchResult],
    ) -> None:
        save_debug = getattr(self.context.controller, "save_annotated_debug", None)
        if save_debug is None:
            return
        boxes = [(*match.bbox, "label") for match in remaining_matches]
        boxes.extend((*match.bbox, "go") for match in challenge_matches)
        if selected is not None:
            boxes.append((*selected.bbox, "status_roi"))
        save_debug(
            "guild_dungeon_outpost_probe",
            screen,
            lines=[
                f"remaining_matches={len(remaining_matches)}",
                f"challenge_matches={len(challenge_matches)}",
                f"selected={selected.center if selected else 'none'}",
            ],
            boxes=boxes,
        )

    def _save_probe_summary(self, debug_dir) -> None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        lines = ["Guild dungeon probe"]
        for record in self.last_probe_records:
            selected = record.selected_center if record.selected_center is not None else "none"
            lines.append(
                f"scan={record.scan_index:02d} node={record.node_kind} "
                f"node_center={record.node_center} node_conf={record.node_confidence:.4f} "
                f"remaining={record.remaining_count} challenge={record.challenge_count} bonus={record.bonus_count} "
                f"selected={selected} selected_conf={record.selected_confidence:.4f}"
            )
        path = debug_dir / "summary.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.last_probe_summary_path = path
