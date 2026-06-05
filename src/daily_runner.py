from __future__ import annotations

from typing import Dict, Iterable, List, Type

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler
from src.config import DEFAULT_SERIAL, TASK_ORDER
from src.daily_task_finder import DailyTaskFinder
from src.navigator import Navigator
from src.scene_detector import SceneDetector
from src.task_runner import TaskContext, TaskRunResult
from src.tasks import TASK_CLASSES
from src.vision_matcher import VisionMatcher


def build_context(serial: str = DEFAULT_SERIAL, debug: bool = False) -> TaskContext:
    controller = DeviceController(serial=serial)
    matcher = VisionMatcher()
    detector = SceneDetector(matcher)
    finder = DailyTaskFinder(controller, matcher)
    navigator = Navigator(controller, matcher, detector, finder)
    battle = BattleHandler(controller, matcher, detector)
    return TaskContext(
        controller=controller,
        matcher=matcher,
        detector=detector,
        finder=finder,
        navigator=navigator,
        battle=battle,
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

    def run_all(self, order: Iterable[str] = TASK_ORDER) -> List[TaskRunResult]:
        results = []
        for key in order:
            results.append(self.run_task(key))
        return results
