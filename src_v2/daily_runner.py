"""
daily_runner.py — 每日任務執行器

職責：
  - DailyRunner：根據 task_key 找到 task class，呼叫對應的 run / run_from_current_daily_screen /
    run_from_current_scene 方法
  - run_all()：依 order 循序執行，ADB stall 時 sleep 後繼續

build_context() 已移至 task_runner.py，此處不重複。
"""
from __future__ import annotations

import time
from typing import Iterable, List

from src.config import RUN_ALL_TASK_ORDER
from src_v2.task_runner import TaskContext, TaskRunResult, TaskState, build_context  # noqa: F401
from src_v2.tasks import TASK_CLASSES


_ADB_STALL_MARKERS = (
    "ADB screenshot timed out",
    "ADB command timed out",
    "screencap",
    "TimeoutExpired",
)


def _is_adb_stall(message: str) -> bool:
    return any(marker in message for marker in _ADB_STALL_MARKERS)


class DailyRunner:
    def __init__(self, context: TaskContext) -> None:
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
        order: Iterable[str] = RUN_ALL_TASK_ORDER,
        *,
        failure_sleep_seconds: float = 60.0,
    ) -> List[TaskRunResult]:
        results = []
        for key in order:
            if key not in TASK_CLASSES:
                # 尚未移植的 task 跳過（不 crash）
                self.context.logger.log(
                    f"run-all skip task={key} (not yet ported to src_v2)", force=True
                )
                continue

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
                if _is_adb_stall(result.message):
                    print(
                        f"[run-all] task={key} failed: {result.message}; "
                        f"ADB may be stalled, sleeping {failure_sleep_seconds:.0f}s",
                        flush=True,
                    )
                    time.sleep(failure_sleep_seconds)
                else:
                    print(f"[run-all] task={key} failed: {result.message}", flush=True)
        return results
