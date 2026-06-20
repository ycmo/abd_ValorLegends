from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Type

from src.adb_controller import DeviceController
from src.battle_handler import BattleHandler
from src.config import (
    DEFAULT_SERIAL,
    RUN_ALL_GO_FIRST_TASK_ORDER,
    TRANSITION_WAIT_SECONDS,
)
from src.daily_task_finder import DailyTaskFinder, TaskSearchStatus
from src.debug_log import DebugLogger
from src.exceptions import MissingAssetError, TaskSkippedError
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

    def run_task_go_first(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        started = time.time()
        missing = task_class(self.context).missing_assets()
        if missing:
            return TaskRunResult(
                task_key=task_key,
                state=TaskState.NEEDS_ASSETS,
                message="Missing assets: " + ", ".join(str(path) for path in missing),
                elapsed_seconds=time.time() - started,
            )
        try:
            opened = self.context.navigator.open_task_from_daily_go_first(TASK_CLASSES[task_key].spec)
            if opened.status.value == "skipped_done_or_claimable":
                return TaskRunResult(task_key, TaskState.SKIPPED, opened.reason, time.time() - started)
            return task_class(self.context)._execute_and_return(started)
        except Exception as exc:
            return TaskRunResult(
                task_key=task_key,
                state=TaskState.FAILED,
                message=f"{type(exc).__name__}: {exc}",
                elapsed_seconds=time.time() - started,
            )

    def run_current_task(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        return task_class(self.context).run_from_current_daily_screen()

    def run_current_scene_task(self, task_key: str) -> TaskRunResult:
        task_class = TASK_CLASSES[task_key]
        return task_class(self.context).run_from_current_scene()

    def run_all(
        self,
        order: Iterable[str] = RUN_ALL_GO_FIRST_TASK_ORDER,
        *,
        failure_sleep_seconds: float = 60.0,
    ) -> List[TaskRunResult]:
        return self.run_all_go_first(
            order,
            log_prefix="run-all",
            failure_sleep_seconds=failure_sleep_seconds,
        )

    def run_all_go_first(
        self,
        order: Iterable[str] = RUN_ALL_GO_FIRST_TASK_ORDER,
        *,
        failure_sleep_seconds: float = 60.0,
        log_prefix: str = "run-all-go-first",
    ) -> List[TaskRunResult]:
        runnable_tasks = set(order)
        handled_tasks: set[str] = set()
        results: List[TaskRunResult] = []
        if not self.context.navigator.go_to_daily_tasks():
            return [
                TaskRunResult(
                    task_key="run-all-go-first",
                    state=TaskState.FAILED,
                    message="Cannot reach daily tasks before go-first scan",
                )
            ]

        task_specs = {task_key: task_class.spec for task_key, task_class in TASK_CLASSES.items()}
        max_scans = 30
        for _scan_index in range(max_scans):
            self.context.logger.log(
                f"{log_prefix} scan handled={','.join(sorted(handled_tasks))}",
                force=True,
            )
            try:
                rows = self.context.finder.scan_current_screen_go_first(task_specs)
            except Exception as exc:
                result = self._failed_result_from_exception(log_prefix, exc)
                results.append(result)
                self._handle_failed_run_all_result(log_prefix, result.task_key, result, failure_sleep_seconds)
                break
            if not rows:
                swipe_result = self._swipe_daily_list_or_failed(log_prefix)
                if isinstance(swipe_result, TaskRunResult):
                    results.append(swipe_result)
                    self._handle_failed_run_all_result(
                        log_prefix,
                        swipe_result.task_key,
                        swipe_result,
                        failure_sleep_seconds,
                    )
                    break
                if not swipe_result:
                    break
                continue

            for row in rows:
                if row.task_key in runnable_tasks and row.result.status == TaskSearchStatus.DONE_OR_CLAIMABLE:
                    task_key = row.task_key
                    if task_key in handled_tasks:
                        continue
                    result = TaskRunResult(
                        task_key=task_key,
                        state=TaskState.SKIPPED,
                        message=row.result.reason,
                    )
                    results.append(result)
                    handled_tasks.add(task_key)
                    self.context.logger.log(
                        f"{log_prefix} skip task={task_key} status={row.status_kind} row_y={row.row_y}",
                        force=True,
                    )

            runnable_row = next(
                (
                    row for row in rows
                    if row.status_kind == "go"
                    and row.task_key in runnable_tasks
                    and row.task_key not in handled_tasks
                    and row.result.go_match is not None
                ),
                None,
            )
            if runnable_row is not None:
                task_key = runnable_row.task_key
                assert task_key is not None
                task_class = TASK_CLASSES[task_key]
                task = task_class(self.context)
                missing = task.missing_assets()
                if missing:
                    result = TaskRunResult(
                        task_key=task_key,
                        state=TaskState.NEEDS_ASSETS,
                        message="Missing assets: " + ", ".join(str(path) for path in missing),
                    )
                    results.append(result)
                    handled_tasks.add(task_key)
                    continue

                self.context.logger.log(
                    f"{log_prefix} start task={task_key} row_y={runnable_row.row_y}",
                    force=True,
                )
                started = time.time()
                try:
                    self.context.controller.tap(*runnable_row.result.go_match.center)
                    time.sleep(TRANSITION_WAIT_SECONDS)
                    result = task._execute_and_return(started)
                except TaskSkippedError as exc:
                    result = TaskRunResult(
                        task_key=task_key,
                        state=TaskState.SKIPPED,
                        message=str(exc),
                        elapsed_seconds=time.time() - started,
                    )
                except MissingAssetError as exc:
                    result = TaskRunResult(
                        task_key=task_key,
                        state=TaskState.NEEDS_ASSETS,
                        message=str(exc),
                        elapsed_seconds=time.time() - started,
                    )
                except Exception as exc:
                    result = TaskRunResult(
                        task_key=task_key,
                        state=TaskState.FAILED,
                        message=f"{type(exc).__name__}: {exc}",
                        elapsed_seconds=time.time() - started,
                    )
                results.append(result)
                handled_tasks.add(task_key)
                self.context.logger.log(
                    f"{log_prefix} result task={task_key} state={result.state.value} "
                    f"elapsed={result.elapsed_seconds:.1f}s message={result.message}",
                    force=True,
                )
                if self._handle_failed_run_all_result(log_prefix, task_key, result, failure_sleep_seconds):
                    break
                continue

            if any(row.status_kind == "completed" for row in rows):
                self.context.logger.log(
                    f"{log_prefix} reached completed section; stopping",
                    force=True,
                )
                break

            swipe_result = self._swipe_daily_list_or_failed(log_prefix)
            if isinstance(swipe_result, TaskRunResult):
                results.append(swipe_result)
                self._handle_failed_run_all_result(
                    log_prefix,
                    swipe_result.task_key,
                    swipe_result,
                    failure_sleep_seconds,
                )
                break
            if not swipe_result:
                break
        return results

    def _swipe_daily_list_or_failed(self, log_prefix: str):
        try:
            return self.context.finder._swipe_until_changed(
                360,
                430,
                360,
                230,
                duration_ms=420,
                wait_seconds=1.0,
            )
        except Exception as exc:
            return self._failed_result_from_exception(log_prefix, exc)

    def _failed_result_from_exception(self, log_prefix: str, exc: Exception) -> TaskRunResult:
        return TaskRunResult(
            task_key=log_prefix,
            state=TaskState.FAILED,
            message=f"{type(exc).__name__}: {exc}",
        )

    def _run_all_with(
        self,
        order: Iterable[str],
        *,
        run_one,
        log_prefix: str,
        failure_sleep_seconds: float,
    ) -> List[TaskRunResult]:
        results = []
        for key in order:
            self.context.logger.log(f"{log_prefix} start task={key}", force=True)
            started = time.time()
            try:
                result = run_one(key)
            except Exception as exc:
                result = TaskRunResult(
                    task_key=key,
                    state=TaskState.FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=time.time() - started,
                )
            results.append(result)
            self.context.logger.log(
                f"{log_prefix} result task={key} state={result.state.value} "
                f"elapsed={result.elapsed_seconds:.1f}s message={result.message}",
                force=True,
            )
            if result.state == TaskState.FAILED:
                self._handle_failed_run_all_result(log_prefix, key, result, failure_sleep_seconds)
        return results

    def _handle_failed_run_all_result(
        self,
        log_prefix: str,
        task_key: str,
        result: TaskRunResult,
        failure_sleep_seconds: float,
    ) -> bool:
        if result.state != TaskState.FAILED:
            return False
        if is_adb_stall_message(result.message):
            print(
                f"[{log_prefix}] task={task_key} failed: {result.message}; "
                f"ADB may be stalled, sleeping {failure_sleep_seconds:.0f}s and stopping run-all",
                flush=True,
            )
            time.sleep(failure_sleep_seconds)
            return True
        else:
            print(f"[{log_prefix}] task={task_key} failed: {result.message}", flush=True)
            return False
