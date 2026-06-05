from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Iterable, Optional, Sequence, Tuple, Type

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler, BattleResult
from src.config import SHARED_ASSETS_DIR, TAP_COOLDOWN_SECONDS, TaskSpec
from src.exceptions import BotError, MissingAssetError, TaskFailedError
from src.daily_task_finder import DailyTaskFinder
from src.navigator import Navigator, OpenTaskStatus
from src.scene_detector import SceneDetector
from src.vision_matcher import VisionMatcher


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


class BaseTask:
    spec: ClassVar[TaskSpec]
    required_assets: ClassVar[Tuple[str, ...]] = ("task_label.png",)

    def __init__(self, context: TaskContext):
        self.context = context

    def run(self) -> TaskRunResult:
        started = time.time()
        return self._run_with_opener(started, self.context.navigator.open_task_from_daily)

    def run_from_current_daily_screen(self) -> TaskRunResult:
        started = time.time()
        return self._run_with_opener(started, self.context.navigator.open_task_from_current_daily_screen)

    def _run_with_opener(self, started: float, opener) -> TaskRunResult:
        missing = self.missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
        )

        try:
            opened = opener(self.spec)
            if opened.status == OpenTaskStatus.SKIPPED_DONE_OR_CLAIMABLE:
                return self._result(TaskState.SKIPPED, opened.reason, started)

            result = self.execute()
            try:
                self.context.navigator.return_to_daily_tasks()
            except BotError as exc:
                return self._result(
                    TaskState.FAILED,
                    f"Task action finished but return_to_daily_tasks failed: {exc}",
                    started,
                )
            return self._result(TaskState.COMPLETED, result or "completed", started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except BotError as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    def execute(self) -> str:
        raise NotImplementedError

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

    def run_steps(self, steps: Iterable[ActionStep]) -> str:
        completed = []
        for step in steps:
            if self.tap_asset(step):
                completed.append(step.name)
        return "steps: " + ", ".join(completed)

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
