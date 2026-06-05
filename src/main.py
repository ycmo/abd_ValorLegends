from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.adb_controller import AdbControllerError, DeviceController
from src.config import CAPTURES_DIR, DEFAULT_SERIAL, EXPECTED_SCREEN_SIZE, TASK_ORDER, TASK_SPECS
from src.daily_runner import DailyRunner, build_context
from src.exceptions import BotError, ConfigurationError
from src.scene_detector import SceneDetector
from src.tasks import TASK_CLASSES
from src.vision_matcher import VisionMatcher


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valor Legends ADB automation")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help=f"ADB serial, default: {DEFAULT_SERIAL}")
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        default=None,
        help="Save before/after screenshots for every tap, swipe, and keyevent under captures/action_debug/",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="List connected ADB devices")
    sub.add_parser("check-device", help="Connect and validate screenshot size")

    screenshot = sub.add_parser("screenshot", help="Capture a screenshot into captures/")
    screenshot.add_argument("--name", help="Optional output file name")

    sub.add_parser("detect-scene", help="Detect current scene from shared anchors")
    sub.add_parser("go-daily", help="Navigate to the daily tasks screen")

    sub.add_parser("list-tasks", help="List configured daily tasks")

    probe_task = sub.add_parser("probe-task", help="Find a task row on the daily-task screen without opening it")
    probe_task.add_argument("task", choices=sorted(TASK_CLASSES))

    probe_current_task = sub.add_parser(
        "probe-current-task",
        help="Find a task row on the current daily-task screen without scrolling",
    )
    probe_current_task.add_argument("task", choices=sorted(TASK_CLASSES))

    run_task = sub.add_parser("run-task", help="Run one task by key")
    run_task.add_argument("task", choices=sorted(TASK_CLASSES))

    run_current_task = sub.add_parser(
        "run-current-task",
        help="Run one visible task row on the current daily-task screen without scrolling first",
    )
    run_current_task.add_argument("task", choices=sorted(TASK_CLASSES))

    sub.add_parser("run-all", help="Run all tasks in configured order")
    return parser


def _connect_controller(serial: str) -> DeviceController:
    controller = DeviceController(serial)
    if not controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    return controller


def cmd_devices() -> int:
    for serial in DeviceController.list_devices():
        print(serial)
    return 0


def cmd_check_device(serial: str) -> int:
    controller = _connect_controller(serial)
    wm_size = controller.get_screen_size()
    density = controller.get_screen_density()
    screenshot_size = controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    print(f"serial={serial}")
    print(f"wm_size={wm_size[0]}x{wm_size[1]}")
    print(f"density={density}")
    print(f"screenshot_size={screenshot_size[0]}x{screenshot_size[1]}")
    return 0


def cmd_screenshot(serial: str, name: str) -> int:
    controller = _connect_controller(serial)
    if not name:
        name = time.strftime("%Y%m%d_%H%M%S.png")
    path = CAPTURES_DIR / name
    controller.save_screenshot(path)
    print(path)
    return 0


def cmd_detect_scene(serial: str) -> int:
    controller = _connect_controller(serial)
    screen = controller.screenshot()
    detection = SceneDetector(VisionMatcher()).detect(screen)
    print(f"scene={detection.scene.value}")
    print(f"confidence={detection.confidence:.4f}")
    if detection.match:
        print(f"template={detection.match.template_path}")
    if detection.reason:
        print(f"reason={detection.reason}")
    return 0


def cmd_go_daily(serial: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    ok = context.navigator.go_to_daily_tasks()
    print("daily_tasks=ok" if ok else "daily_tasks=failed")
    return 0 if ok else 1


def cmd_list_tasks() -> int:
    for key in TASK_ORDER:
        spec = TASK_SPECS[key]
        print(f"{key}: {spec.display_name} [{spec.kind}]")
        print(f"  policy: {spec.policy.notes}")
    return 0


def cmd_probe_task(serial: str, task_key: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    if not context.navigator.go_to_daily_tasks():
        raise ConfigurationError("Cannot reach daily tasks")
    result = context.finder.scroll_to_task(TASK_SPECS[task_key])
    print(f"task={task_key}")
    print(f"status={result.status.value}")
    if result.label_match:
        print(f"label_center={result.label_match.center}")
        print(f"label_confidence={result.label_match.confidence:.4f}")
    if result.go_match:
        print(f"go_center={result.go_match.center}")
        print(f"go_confidence={result.go_match.confidence:.4f}")
    if result.reason:
        print(f"reason={result.reason}")
    return 0


def cmd_probe_current_task(serial: str, task_key: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = context.finder.find_on_current_screen(TASK_SPECS[task_key])
    print(f"task={task_key}")
    print(f"status={result.status.value}")
    if result.label_match:
        print(f"label_center={result.label_match.center}")
        print(f"label_confidence={result.label_match.confidence:.4f}")
    if result.go_match:
        print(f"go_center={result.go_match.center}")
        print(f"go_confidence={result.go_match.confidence:.4f}")
    if result.reason:
        print(f"reason={result.reason}")
    return 0


def cmd_run_task(serial: str, task_key: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_task(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_current_task(serial: str, task_key: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_current_task(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_all(serial: str, debug_actions: Optional[bool] = None) -> int:
    context = build_context(serial, debug=debug_actions)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    results = DailyRunner(context).run_all()
    failed = False
    for result in results:
        print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
        if result.message:
            print(f"  {result.message}")
        if result.state.value == "failed":
            failed = True
    return 1 if failed else 0


def main(argv: list = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            return cmd_devices()
        if args.command == "check-device":
            return cmd_check_device(args.serial)
        if args.command == "screenshot":
            return cmd_screenshot(args.serial, args.name)
        if args.command == "detect-scene":
            return cmd_detect_scene(args.serial)
        if args.command == "go-daily":
            return cmd_go_daily(args.serial, args.debug_actions)
        if args.command == "list-tasks":
            return cmd_list_tasks()
        if args.command == "probe-task":
            return cmd_probe_task(args.serial, args.task, args.debug_actions)
        if args.command == "probe-current-task":
            return cmd_probe_current_task(args.serial, args.task, args.debug_actions)
        if args.command == "run-task":
            return cmd_run_task(args.serial, args.task, args.debug_actions)
        if args.command == "run-current-task":
            return cmd_run_current_task(args.serial, args.task, args.debug_actions)
        if args.command == "run-all":
            return cmd_run_all(args.serial, args.debug_actions)
        parser.error(f"Unknown command: {args.command}")
        return 2
    except (AdbControllerError, BotError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
