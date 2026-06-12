from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Type

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler
from src.config import DEFAULT_SERIAL, TASK_ORDER
from src.daily_task_finder import DailyTaskFinder
from src.debug_log import DebugLogger
from src.navigator import Navigator
from src.scene_detector import SceneDetector
from src.task_runner import TaskContext, TaskRunResult, TaskState
from src.tasks import TASK_CLASSES
from src.vision_matcher import VisionMatcher


ADB_STALL_MARKERS = (
    "ADB screenshot timed out",
    "ADB command timed out",
    "screencap",
    "TimeoutExpired",
)


def is_adb_stall_message(message: str) -> bool:
    return any(marker in message for marker in ADB_STALL_MARKERS)


def build_context(
    serial: str = DEFAULT_SERIAL,
    debug: Optional[bool] = None,
    console_debug: bool = False,
) -> TaskContext:
    logger = DebugLogger(console_debug)
    controller = DeviceController(serial=serial, debug_actions=debug, logger=logger)
    matcher = VisionMatcher()
    detector = SceneDetector(matcher)
    finder = DailyTaskFinder(controller, matcher, logger=logger)
    navigator = Navigator(controller, matcher, detector, finder, logger=logger)
    battle = BattleHandler(controller, matcher, detector)
    return TaskContext(
        controller=controller,
        matcher=matcher,
        detector=detector,
        finder=finder,
        navigator=navigator,
        battle=battle,
        logger=logger,
    )


class DailyRunner:
    def __init__(self, context: TaskContext):
        self.context = context

    def run_task(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        return task_class(self.context).run()

    def run_current_task(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        return task_class(self.context).run_from_current_daily_screen()

    def run_current_scene_task(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        return task_class(self.context).run_from_current_scene()

    def run_all(
        self,
        order: Iterable[str] = TASK_ORDER,
        *,
        failure_sleep_seconds: float = 60.0,
    ) -> List[TaskRunResult]:
        results = []
        for key in order:
            self.context.logger.log(f"run-all start task={key}", force=True)
            started = time.time()
            try:
                result = self.run_task(key)
            except Exception as exc:
                result = TaskRunResult(
                    task_key=key,
                    state=TaskState.FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=time.time() - started,
                )
            results.append(result)
            self.context.logger.log(
                f"run-all result task={key} state={result.state.value} "
                f"elapsed={result.elapsed_seconds:.1f}s message={result.message}",
                force=True,
            )
            if result.state == TaskState.FAILED:
                if is_adb_stall_message(result.message):
                    print(
                        f"[run-all] task={key} failed: {result.message}; "
                        f"ADB may be stalled, sleeping {failure_sleep_seconds:.0f}s before next task",
                        flush=True,
                    )
                    time.sleep(failure_sleep_seconds)
                else:
                    print(f"[run-all] task={key} failed: {result.message}", flush=True)
        return results
