from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Iterable, Optional, Sequence, Tuple, Type

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler, BattleResult
from src.config import SHARED_ASSETS_DIR, TAP_COOLDOWN_SECONDS, TaskSpec
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.daily_task_finder import DailyTaskFinder
from src.navigator import Navigator, OpenTaskStatus
from src.scene_detector import SceneDetector
from src.vision_matcher import MatchResult, Roi, VisionMatcher
from src.debug_log import DebugLogger


class TaskState(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    NEEDS_ASSETS = "needs_assets"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskRunResult:
    task_key: str
    state: TaskState
    message: str = ""
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class TaskContext:
    controller: DeviceController
    matcher: VisionMatcher
    detector: SceneDetector
    finder: DailyTaskFinder
    navigator: Navigator
    battle: BattleHandler
    logger: DebugLogger
    blocker: object | None = None


@dataclass(frozen=True)
class ActionStep:
    name: str
    asset_name: str
    source: str = "task"  # task or shared
    optional: bool = False
    threshold: float = 0.80
    find_timeout_seconds: float = 3.0
    poll_interval_seconds: float = 0.5
    wait_after_seconds: float = TAP_COOLDOWN_SECONDS


@dataclass(frozen=True)
class TaskSceneAnchor:
    asset_name: str
    source: str = "task"
    threshold: float = 0.82
    roi: Optional[Tuple[int, int, int, int]] = None


class BaseTask:
    spec: ClassVar[TaskSpec]
    required_assets: ClassVar[Tuple[str, ...]] = ("task_label.png",)
    task_scene_anchors: ClassVar[Sequence[TaskSceneAnchor]] = ()

    def __init__(self, context: TaskContext):
        self.context = context
        if not hasattr(self.context, "logger"):
            self.context.logger = DebugLogger(False)

    def run(self) -> TaskRunResult:
        started = time.time()
        return self._run_with_opener(
            started,
            self.context.navigator.open_task_from_daily,
            allow_current_scene=True,
        )

    def run_from_current_daily_screen(self) -> TaskRunResult:
        started = time.time()
        return self._run_with_opener(
            started,
            self.context.navigator.open_task_from_current_daily_screen,
            allow_current_scene=False,
        )

    def run_from_current_scene(self) -> TaskRunResult:
        started = time.time()
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
            )

        try:
            if not self.is_current_task_scene():
                raise TaskFailedError(f"Current screen is not the {self.spec.display_name} task scene")
            return self._execute_and_return(started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except BotError as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def _run_with_opener(self, started: float, opener, *, allow_current_scene: bool) -> TaskRunResult:
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
        )

        try:
            if allow_current_scene and self.is_current_task_scene():
                return self._execute_and_return(started)

            opened = opener(self.spec)
            if opened.status == OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE:
                return self._result(TaskState.SKIPPED, opened.reason, started)

            return self._execute_and_return(started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except BotError as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        raise NotImplementedError

    def execute_from_current_scene(self) -> str:
        return self.execute()

    def is_current_task_scene(self) -> bool:
        screen = self.context.controller.screenshot()
        return self.is_task_scene(screen)

    def is_task_scene(self, screen) -> bool:
        for anchor in self.task_scene_anchors:
            path = self.asset_path(anchor.asset_name, anchor.source)
            if not path.exists():
                continue
            match = self.context.matcher.match_template(
                screen,
                path,
                threshold=anchor.threshold,
                roi=anchor.roi,
            )
            if match is not None:
                return True
        return False

    def missing_assets(self) -> Tuple[Path, ...]:
        missing = []
        for name in self.required_assets:
            path = self.asset_path(name)
            if not path.exists():
                missing.append(path)
        if not (SHARED_ASSETS_DIR / "go_button.png").exists():
            missing.append(SHARED_ASSETS_DIR / "go_button.png")
        return tuple(missing)

    def asset_path(self, name: str, source: str = "task") -> Path:
        if source == "shared":
            return SHARED_ASSETS_DIR / name
        return self.spec.asset_dir / name

    def tap_asset(self, step: ActionStep) -> bool:
        path = self.asset_path(step.asset_name, step.source)
        if not path.exists():
            if step.optional:
                return False
            raise MissingAssetError(f"Missing template for step {step.name}: {path}")

        deadline = time.time() + step.find_timeout_seconds
        match = None
        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, path, threshold=step.threshold)
            if match is not None:
                break
            time.sleep(step.poll_interval_seconds)

        if match is None:
            if step.optional:
                return False
            raise TaskFailedError(f"Template not found for step {step.name}: {path}")

        self.context.controller.tap(*match.center)
        time.sleep(step.wait_after_seconds)
        return True

    def wait_while_busy(
        self,
        *,
        label: str = "busy overlay",
        max_seconds: float = 20.0,
        poll_seconds: float = 1.0,
        roi: Roi = (400, 180, 180, 180),
        threshold: float = 0.86,
    ) -> None:
        waited = 0.0
        logged = False
        while waited < max_seconds:
            screen = self.context.controller.screenshot()
            if not self._is_busy_overlay(screen, roi=roi, threshold=threshold):
                if logged:
                    self._log(f"{label} cleared after {waited:.1f}s")
                return
            if not logged:
                self._log(f"{label} detected; waiting")
                logged = True
            time.sleep(poll_seconds)
            waited += poll_seconds
        raise TaskFailedError(f"{label} did not clear within {max_seconds:.0f}s")

    def tap_match_until_gone(
        self,
        match: MatchResult,
        *,
        label: str,
        threshold: float,
        max_taps: int = 4,
        wait_seconds: float = TAP_COOLDOWN_SECONDS,
        roi_padding: int = 20,
        confidence_drop: float = 0.10,
    ) -> None:
        bx, by, bw, bh = match.bbox
        roi = (
            max(0, bx - roi_padding),
            max(0, by - roi_padding),
            bw + roi_padding * 2,
            bh + roi_padding * 2,
        )
        points = self._tap_retry_points(match)
        for index in range(max_taps):
            point = points[min(index, len(points) - 1)]
            self.context.controller.annotate_next_tap_debug(
                lines=[
                    f"{label} tap {index + 1}/{max_taps}",
                    f"{match.template_path.name} confidence={match.confidence:.3f}",
                ],
                boxes=[(*match.bbox, "go")],
            )
            self.context.controller.tap(*point)
            time.sleep(wait_seconds)
            self.wait_while_busy(label=f"{label} busy", max_seconds=20.0)
            screen = self.context.controller.screenshot()
            result = self.context.matcher.match_template(
                screen,
                match.template_path,
                threshold=threshold,
                roi=roi,
                check_brightness=False,
            )
            if result is None or result.confidence < match.confidence - confidence_drop:
                confidence_text = "not_found" if result is None else f"{result.confidence:.3f}"
                self._log(
                    f"{label} confirmed gone after tap {index + 1}; "
                    f"template={match.template_path.name} confidence={confidence_text}"
                )
                return
            self._log(
                f"{label} still visible after tap {index + 1}; "
                f"template={match.template_path.name} confidence={result.confidence:.3f}"
            )
        raise TaskFailedError(f"{label} did not disappear after {max_taps} taps: {match.template_path.name}")

    def _is_busy_overlay(
        self,
        screen,
        *,
        roi: Roi = (400, 180, 180, 180),
        threshold: float = 0.86,
    ) -> bool:
        path = SHARED_ASSETS_DIR / "busy_waiting_overlay.png"
        if not path.exists():
            return False
        return self.context.matcher.match_template(
            screen,
            path,
            threshold=threshold,
            roi=roi,
            check_brightness=False,
        ) is not None

    def _log(self, message: str) -> None:
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.log(message, force=True)

    @staticmethod
    def _tap_retry_points(match: MatchResult) -> Sequence[Tuple[int, int]]:
        x, y = match.center
        bx, by, bw, bh = match.bbox
        inset_x = max(2, min(12, bw // 4))
        inset_y = max(2, min(12, bh // 4))
        return (
            (x, y),
            (bx + inset_x, by + inset_y),
            (bx + bw - inset_x, by + bh - inset_y),
            (bx + inset_x, by + bh - inset_y),
            (bx + bw - inset_x, by + inset_y),
        )

    def run_steps(self, steps: Iterable[ActionStep]) -> str:
        completed = []
        for step in steps:
            if self.tap_asset(step):
                completed.append(step.name)
        return "steps: " + ", ".join(completed)

    def dismiss_reward_overlay_by_blank_taps(
        self,
        *,
        is_closed=None,
        max_taps: int = 2,
        tap_points: Sequence[Tuple[int, int]] = ((80, 500),),
        wait_seconds: float = TAP_COOLDOWN_SECONDS,
        failure_message: str = "Reward overlay did not close after blank-area taps",
    ) -> None:
        """Dismiss common reward overlays by tapping blank/outside areas."""
        if is_closed is not None and is_closed():
            return
        if self.handle_known_blocker_once():
            if is_closed is None or is_closed():
                return

        for index in range(max_taps):
            point = tap_points[min(index, len(tap_points) - 1)]
            self.context.controller.tap(*point)
            time.sleep(wait_seconds)
            if self.handle_known_blocker_once():
                if is_closed is None or is_closed():
                    return
            if is_closed is not None and is_closed():
                return

        if is_closed is None:
            return
        raise TaskFailedError(failure_message)

    def handle_known_blocker_once(self, screen=None) -> bool:
        blocker = getattr(self.context, "blocker", None)
        if blocker is None:
            return False
        return bool(blocker.handle_known_blocker(screen))

    def handle_known_blocker_before_scan(self, screen=None) -> bool:
        """Handle a visible blocker before task recognition or scrolling.

        If the blocker is visibly present but still reports failure after tapping,
        callers should still discard the current screen and retry from a fresh
        screenshot instead of continuing recognition on a blocked view.
        """
        blocker = getattr(self.context, "blocker", None)
        if blocker is None:
            return False
        if self._known_blocker_visible(blocker, screen):
            blocker.handle_known_blocker(screen)
            return True
        return bool(blocker.handle_known_blocker(screen))

    @staticmethod
    def _known_blocker_visible(blocker: object, screen) -> bool:
        if screen is None:
            return False
        for method_name in ("match_reward_acquired", "match_popup_close", "match_gift_pack"):
            method = getattr(blocker, method_name, None)
            if method is None:
                continue
            if method(screen) is not None:
                return True
        return False

    def _execute_and_return(self, started: float) -> TaskRunResult:
        result = self.execute_from_current_scene()
        try:
            self.context.navigator.return_to_daily_tasks()
        except BotError as exc:
            return self._result(
                TaskState.FAILED,
                f"Task action finished but return_to_daily_tasks failed: {exc}",
                started,
            )
        return self._result(TaskState.COMPLETED, result or "completed", started)

    def _result(self, state: TaskState, message: str, started: float) -> TaskRunResult:
        return TaskRunResult(
            task_key=self.spec.key,
            state=state,
            message=message,
            elapsed_seconds=time.time() - started,
        )


class AssetSequenceTask(BaseTask):
    steps: ClassVar[Sequence[ActionStep]] = ()

    def execute(self) -> str:
        return self.run_steps(self.steps)


class BattleOnceTask(BaseTask):
    required_assets: ClassVar[Tuple[str, ...]] = ("task_label.png", "challenge_button.png")
    battle_timeout_seconds: ClassVar[float] = 150.0
    win_required: ClassVar[bool] = False

    def execute(self) -> str:
        self.context.battle.tap_challenge(self.spec.asset_dir)
        result = self.context.battle.wait_for_result(self.battle_timeout_seconds)
        if result == BattleResult.TIMEOUT:
            raise TaskFailedError("Timed out waiting for battle result")
        if self.win_required and result != BattleResult.WIN:
            raise TaskFailedError(f"Battle result is not a win: {result.value}")
        self.context.battle.dismiss_result()
        return f"battle_result={result.value}"
