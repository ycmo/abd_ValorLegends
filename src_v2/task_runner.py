"""
task_runner.py — src_v2 核心執行層

定義：
  TaskState, TaskRunResult        — 執行結果（src_v2 自己定義，不從 src/ import）
  TaskContext                     — 所有 task 共用的依賴容器（含 DebugCapture）
  build_context()                 — TaskContext 工廠函式
  BaseTask                        — 所有 task 的父類，提供統一底層 API
  AssetSequenceTask               — 簡單步驟型 task 的基類
  BattleOnceTask                  — 戰鬥型 task 的基類

BaseTask 統一 API（取代各 task 各自 copy 的 boilerplate）：

  _wait_for(asset_name, *, source, roi, threshold, timeout_seconds, poll_interval)
    → Optional[MatchResult]
    追蹤 best_confidence；超時時若 debug_capture 啟用，自動呼叫 save_failure()

  _require(label, asset_name, **kwargs) → MatchResult
    找不到時 raise TaskFailedError，錯誤訊息含 debug 截圖路徑

  _tap(label, asset_name, *, wait_after, **kwargs) → MatchResult
    _require + controller.tap + sleep

  _is_scene(scene) → bool
  _wait_for_scene(scene, timeout_seconds) → bool

  _log(message) → None
  _return_to_daily() → None   (通用返回策略)
  _pre_return_hook() → None   (task 可 override 的前置 hook)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Iterable, Optional, Sequence, Tuple

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler, BattleResult
from src.config import (
    CAPTURES_DIR,
    DEFAULT_SERIAL,
    SHARED_ASSETS_DIR,
    TAP_COOLDOWN_SECONDS,
    TaskSpec,
)
from src.daily_task_finder import DailyTaskFinder
from src.debug_log import DebugLogger
from src.exceptions import BotError, MissingAssetError, TaskFailedError, TaskSkippedError
from src.navigator import Navigator, OpenTaskStatus
from src.scene_detector import Scene, SceneDetector
from src.vision_matcher import MatchResult, Roi, VisionMatcher
from src_v2.debug_capture import DebugCapture


# ---------------------------------------------------------------------------
# 執行結果
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# TaskContext — 所有依賴的容器（含 DebugCapture）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskContext:
    controller: DeviceController
    matcher: VisionMatcher
    detector: SceneDetector
    finder: DailyTaskFinder
    navigator: Navigator
    battle: BattleHandler
    logger: DebugLogger
    debug_capture: DebugCapture


def build_context(
    serial: str = DEFAULT_SERIAL,
    debug: Optional[bool] = None,
    console_debug: bool = False,
) -> TaskContext:
    """TaskContext 工廠：建立所有依賴並組裝。"""
    logger = DebugLogger(console_debug)
    controller = DeviceController(serial=serial, debug_actions=debug, logger=logger)
    matcher = VisionMatcher()
    detector = SceneDetector(matcher)
    finder = DailyTaskFinder(controller, matcher, logger=logger)
    navigator = Navigator(controller, matcher, detector, finder, logger=logger)
    battle = BattleHandler(controller, matcher, detector)
    debug_capture = DebugCapture.create(CAPTURES_DIR, enabled=True)
    return TaskContext(
        controller=controller,
        matcher=matcher,
        detector=detector,
        finder=finder,
        navigator=navigator,
        battle=battle,
        logger=logger,
        debug_capture=debug_capture,
    )


# ---------------------------------------------------------------------------
# TaskSceneAnchor — task 畫面識別用
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSceneAnchor:
    asset_name: str
    source: str = "task"
    threshold: float = 0.82
    roi: Optional[Roi] = None


# ---------------------------------------------------------------------------
# BaseTask
# ---------------------------------------------------------------------------


class BaseTask:
    """
    所有 src_v2 task 的父類。

    子類只需定義：
      spec                — ClassVar[TaskSpec]
      required_assets     — 必要 asset 檔名 tuple
      task_scene_anchors  — 場景識別 anchor tuple
      execute()           — 業務邏輯（在 task 畫面上的操作）

    不得在子類自行實作 _match / _require / _tap 的 poll loop。
    """

    spec: ClassVar[TaskSpec]
    required_assets: ClassVar[Tuple[str, ...]] = ("task_label.png",)
    task_scene_anchors: ClassVar[Sequence[TaskSceneAnchor]] = ()
    _POLL_INTERVAL: ClassVar[float] = 0.35

    def __init__(self, context: TaskContext) -> None:
        self.context = context

    # ------------------------------------------------------------------
    # 公開進入點（由 DailyRunner 呼叫）
    # ------------------------------------------------------------------

    def run(self) -> TaskRunResult:
        """從 daily tasks 畫面開始，完整跑完一個 task。"""
        started = time.time()
        return self._run_with_opener(
            started,
            self.context.navigator.open_task_from_daily,
            allow_current_scene=True,
        )

    def run_from_current_daily_screen(self) -> TaskRunResult:
        """從當前 daily tasks 畫面（不滾動）開始。"""
        started = time.time()
        return self._run_with_opener(
            started,
            self.context.navigator.open_task_from_current_daily_screen,
            allow_current_scene=False,
        )

    def run_from_current_scene(self) -> TaskRunResult:
        """從 task 的功能畫面（已進入）直接執行。"""
        started = time.time()
        missing = self._missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
            )
        try:
            if not self._is_current_task_scene():
                raise TaskFailedError(
                    f"Current screen is not the {self.spec.display_name} task scene"
                )
            return self._execute_and_return(started)
        except TaskSkippedError as exc:
            return self._result(TaskState.SKIPPED, str(exc), started)
        except MissingAssetError as exc:
            return self._result(TaskState.NEEDS_ASSETS, str(exc), started)
        except BotError as exc:
            return self._result(TaskState.FAILED, str(exc), started)

    # ------------------------------------------------------------------
    # 子類需 override 的方法
    # ------------------------------------------------------------------

    def execute(self) -> str:
        raise NotImplementedError

    def execute_from_current_scene(self) -> str:
        """預設直接呼叫 execute()；有前置場景邏輯的 task 可 override。"""
        return self.execute()

    def _pre_return_hook(self) -> None:
        """返回 daily tasks 前的前置動作。預設 no-op；task 視需要 override。"""

    # ------------------------------------------------------------------
    # 統一底層 API：_wait_for / _require / _tap
    # ------------------------------------------------------------------

    def _wait_for(
        self,
        asset_name: str,
        *,
        source: str = "task",
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
        poll_interval: float = _POLL_INTERVAL,
    ) -> Optional[MatchResult]:
        """
        Poll loop：在 timeout 內持續截圖並做模板匹配。
        追蹤 best_confidence；超時時若 debug_capture 啟用，自動儲存失敗截圖。

        回傳：MatchResult（成功）或 None（超時）
        """
        path = self._asset_path(asset_name, source)
        deadline = time.time() + timeout_seconds
        best: Optional[MatchResult] = None
        last_screen: Optional[object] = None

        while time.time() <= deadline:
            screen = self.context.controller.screenshot()
            last_screen = screen
            match = self.context.matcher.match_template(
                screen, path, threshold=threshold, roi=roi
            )
            if match is not None:
                return match
            # 追蹤 best confidence（供失敗截圖使用）
            probe = self.context.matcher.best_template_match(screen, path, roi=roi)
            if probe is not None and (best is None or probe.confidence > best.confidence):
                best = probe
            time.sleep(poll_interval)

        # 超時 → 儲存失敗截圖
        if last_screen is not None:
            self.context.debug_capture.save_failure(
                screen=last_screen,
                task_key=self.spec.key,
                step_label=asset_name,
                roi=roi,
                best_confidence=best.confidence if best else None,
                threshold=threshold,
            )
        return None

    def _require(
        self,
        label: str,
        asset_name: str,
        *,
        source: str = "task",
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
    ) -> MatchResult:
        """
        _wait_for 的強制版本：找不到時 raise TaskFailedError。
        錯誤訊息含 debug 截圖路徑。
        """
        match = self._wait_for(
            asset_name,
            source=source,
            roi=roi,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
        if match is None:
            # 失敗截圖已在 _wait_for 內儲存
            debug_path = ""
            last_path = self.context.debug_capture.last_failure_path
            if last_path:
                try:
                    # 嘗試擷取 captures/... 之後的部分
                    parts = last_path.parts
                    if "captures" in parts:
                        idx = parts.index("captures")
                        # 替換實際 session id 為 latest
                        rel_parts = list(parts[idx:])
                        if len(rel_parts) > 2 and rel_parts[1] == "sessions":
                            rel_parts[2] = "latest"
                        debug_path = "/".join(rel_parts)
                    else:
                        debug_path = str(last_path)
                except Exception:
                    debug_path = str(last_path)

            raise TaskFailedError(
                f"{label} not found\n"
                f"  debug: {debug_path}"
            )
        return match

    def _tap(
        self,
        label: str,
        asset_name: str,
        *,
        source: str = "task",
        roi: Optional[Roi] = None,
        threshold: float = 0.82,
        timeout_seconds: float = 3.0,
        wait_after: float = TAP_COOLDOWN_SECONDS,
    ) -> MatchResult:
        """_require + controller.tap + sleep。"""
        match = self._require(
            label,
            asset_name,
            source=source,
            roi=roi,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
        self.context.controller.tap(*match.center)
        time.sleep(wait_after)
        return match

    # ------------------------------------------------------------------
    # 場景判斷
    # ------------------------------------------------------------------

    def _is_scene(self, scene: Scene) -> bool:
        screen = self.context.controller.screenshot()
        return self.context.detector.detect(screen).scene == scene

    def _wait_for_scene(self, scene: Scene, timeout_seconds: float = 5.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            if self._is_scene(scene):
                return True
            time.sleep(self._POLL_INTERVAL)
        return False

    def _is_daily_tasks_visible(self) -> bool:
        return self._is_scene(Scene.DAILY_TASKS)

    def _is_current_task_scene(self) -> bool:
        screen = self.context.controller.screenshot()
        return self._is_task_scene(screen)

    def _is_task_scene(self, screen) -> bool:
        for anchor in self.task_scene_anchors:
            path = self._asset_path(anchor.asset_name, anchor.source)
            if not path.exists():
                continue
            match = self.context.matcher.match_template(
                screen, path, threshold=anchor.threshold, roi=anchor.roi
            )
            if match is not None:
                return True
        return False

    # ------------------------------------------------------------------
    # 返回策略
    # ------------------------------------------------------------------

    def _return_to_daily(self) -> None:
        """
        通用返回 Daily Tasks 策略：
          1. 已在 DAILY_TASKS → 直接返回
          2. 呼叫 _pre_return_hook()（task 特殊前置）
          3. 再次檢查是否在 DAILY_TASKS → 直接返回
          4. navigator.return_to_daily_tasks()
          5. 以上均失敗 → raise TaskFailedError
        """
        if self._is_daily_tasks_visible():
            return
        self._pre_return_hook()
        if self._is_daily_tasks_visible():
            return
        if self.context.navigator.return_to_daily_tasks():
            return
        raise TaskFailedError(
            f"{self.spec.display_name} completed, but could not return to Daily Tasks"
        )

    # ------------------------------------------------------------------
    # Overlay 解除
    # ------------------------------------------------------------------

    def _dismiss_overlay_by_blank_taps(
        self,
        *,
        is_closed=None,
        max_taps: int = 2,
        tap_points: Sequence[Tuple[int, int]] = ((80, 500),),
        wait_seconds: float = TAP_COOLDOWN_SECONDS,
        failure_message: str = "Reward overlay did not close after blank-area taps",
    ) -> None:
        """點擊空白區域解除 overlay（獎勵彈窗等）。"""
        if is_closed is not None and is_closed():
            return
        for index in range(max_taps):
            point = tap_points[min(index, len(tap_points) - 1)]
            self.context.controller.tap(*point)
            time.sleep(wait_seconds)
            if is_closed is not None and is_closed():
                return
        if is_closed is None:
            return
        raise TaskFailedError(failure_message)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        self.context.logger.log(message, force=True)

    def _asset_path(self, name: str, source: str = "task") -> Path:
        if source == "shared":
            return SHARED_ASSETS_DIR / name
        return self.spec.asset_dir / name

    def _missing_assets(self) -> Tuple[Path, ...]:
        missing = []
        for name in self.required_assets:
            path = self._asset_path(name)
            if not path.exists():
                missing.append(path)
        if not (SHARED_ASSETS_DIR / "go_button.png").exists():
            missing.append(SHARED_ASSETS_DIR / "go_button.png")
        return tuple(missing)

    # ------------------------------------------------------------------
    # 內部共用（run flow）
    # ------------------------------------------------------------------

    def _run_with_opener(self, started: float, opener, *, allow_current_scene: bool) -> TaskRunResult:
        missing = self._missing_assets()
        if missing:
            return self._result(
                TaskState.NEEDS_ASSETS,
                "Missing assets: " + ", ".join(str(p) for p in missing),
                started,
            )
        try:
            if allow_current_scene and self._is_current_task_scene():
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

    def _execute_and_return(self, started: float) -> TaskRunResult:
        result = self.execute_from_current_scene()
        try:
            self._return_to_daily()
        except BotError as exc:
            return self._result(
                TaskState.FAILED,
                f"Task action finished but return to daily tasks failed: {exc}",
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


# ---------------------------------------------------------------------------
# AssetSequenceTask — 步驟型 task 基類
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionStep:
    name: str
    asset_name: str
    source: str = "task"
    optional: bool = False
    threshold: float = 0.80
    timeout_seconds: float = 3.0
    wait_after: float = TAP_COOLDOWN_SECONDS


class AssetSequenceTask(BaseTask):
    """各步驟依序 tap asset 的簡單 task。"""

    steps: ClassVar[Sequence[ActionStep]] = ()

    def execute(self) -> str:
        completed = []
        for step in self.steps:
            match = self._wait_for(
                step.asset_name,
                source=step.source,
                threshold=step.threshold,
                timeout_seconds=step.timeout_seconds,
            )
            if match is None:
                if step.optional:
                    continue
                raise TaskFailedError(f"Required step not found: {step.name}")
            self.context.controller.tap(*match.center)
            time.sleep(step.wait_after)
            completed.append(step.name)
        return "steps: " + ", ".join(completed)


# ---------------------------------------------------------------------------
# BattleOnceTask — 戰鬥型 task 基類
# ---------------------------------------------------------------------------


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
