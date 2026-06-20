from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.adb_controller import AdbControllerError, DeviceController
from src.config import (
    CAPTURES_DIR,
    DEFAULT_SERIAL,
    EXPECTED_SCREEN_SIZE,
    RUN_ALL_TASKS_CONFIG,
    TASK_ORDER,
    TASK_SPECS,
    TESTED_DAILY_TASK_ORDER,
    load_run_all_task_order,
)
from src.daily_runner import DailyRunner, build_context
from src.exceptions import BotError, ConfigurationError
from src.paint_cropper import run_paint_crop_workflow
from src.scene_detector import SceneDetector
from src.tasks import TASK_CLASSES
from src.vision_matcher import VisionMatcher


def _task_help_text() -> str:
    lines = ["Available task keys:"]
    for key in TASK_ORDER:
        spec = TASK_SPECS[key]
        lines.append(f"  {key:<14} {spec.display_name}")
    independent_keys = [key for key in sorted(TASK_CLASSES) if key not in TASK_ORDER]
    if independent_keys:
        lines.append("")
        lines.append("Independent task keys:")
        for key in independent_keys:
            spec = TASK_SPECS[key]
            lines.append(f"  {key:<14} {spec.display_name}")
    return "\n".join(lines)


def _add_task_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "task",
        choices=sorted(TASK_CLASSES),
        metavar="task",
        help="Task key. Run list-tasks for policy details.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Valor Legends ADB automation",
        epilog=(
            "Single-task commands:\n"
            "  run-task task\n"
            "  run-task-go-first task\n"
            "  run-current-task task\n"
            "  run-current-scene-task task\n\n"
            f"{_task_help_text()}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help=f"ADB serial, default: {DEFAULT_SERIAL}")
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        default=None,
        help="Save before/after screenshots for every tap, swipe, and keyevent under captures/action_debug/",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose progress logs to the console without saving extra screenshots.",
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
    _add_task_argument(probe_task)

    probe_current_task = sub.add_parser(
        "probe-current-task",
        help="Find a task row on the current daily-task screen without scrolling",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(probe_current_task)

    probe_task_go_first = sub.add_parser(
        "probe-task-go-first",
        help="Find a task row by scanning Go buttons first, without opening it",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(probe_task_go_first)

    probe_current_task_go_first = sub.add_parser(
        "probe-current-task-go-first",
        help="Find a task row on the current daily-task screen by scanning Go buttons first",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(probe_current_task_go_first)

    run_task = sub.add_parser(
        "run-task",
        help="Run one task by key",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(run_task)

    run_task_go_first = sub.add_parser(
        "run-task-go-first",
        help="Run one task by key using Go-first daily row search",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(run_task_go_first)

    run_current_task = sub.add_parser(
        "run-current-task",
        help="Run one task near the current daily-task viewport without resetting the list first",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(run_current_task)

    run_current_scene_task = sub.add_parser(
        "run-current-scene-task",
        help="Continue one task from its current feature screen/dialog",
        epilog=_task_help_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_task_argument(run_current_scene_task)

    sub.add_parser("run-tested-daily", help="Run only the live-tested daily-task closed loops")
    sub.add_parser("run-all", help=f"Run configured tasks using Go-first search ({RUN_ALL_TASKS_CONFIG})")
    sub.add_parser(
        "probe-guild-dungeon-target",
        help="From the current guild dungeon map, select the preferred outpost/challenge target",
    )
    sub.add_parser(
        "probe-abyss-rental-scan",
        help="From the current Abyss rental screen, scan forest-rental rows and print OCR/debug output",
    )
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
    print(f"serial={controller.serial}")
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
    saved = run_paint_crop_workflow(path)
    if saved:
        print("saved_crops:")
        for saved_path in saved:
            print(f"  {saved_path}")
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


def cmd_go_daily(serial: str, debug_actions: Optional[bool] = None, console_debug: bool = False) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
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


def cmd_probe_task(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
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


def cmd_probe_current_task(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
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


def _print_task_search_result(task_key: str, result) -> None:
    print(f"task={task_key}")
    print(f"status={result.status.value}")
    if result.label_match:
        print(f"label_center={result.label_match.center}")
        print(f"label_confidence={result.label_match.confidence:.4f}")
        print(f"label_template={result.label_match.template_path.name}")
    if result.go_match:
        print(f"go_center={result.go_match.center}")
        print(f"go_confidence={result.go_match.confidence:.4f}")
    if result.reason:
        print(f"reason={result.reason}")


def cmd_probe_task_go_first(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    if not context.navigator.go_to_daily_tasks():
        raise ConfigurationError("Cannot reach daily tasks")
    result = context.finder.scroll_to_task_go_first(TASK_SPECS[task_key])
    _print_task_search_result(task_key, result)
    return 0


def cmd_probe_current_task_go_first(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = context.finder.find_on_current_screen_go_first(TASK_SPECS[task_key])
    _print_task_search_result(task_key, result)
    return 0


def cmd_run_task(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_task(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_task_go_first(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_task_go_first(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_current_task(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_current_task(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_current_scene_task(
    serial: str,
    task_key: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    result = DailyRunner(context).run_current_scene_task(task_key)
    print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
    if result.message:
        print(result.message)
    return 0 if result.state.value in ("completed", "skipped", "needs_assets") else 1


def cmd_run_all(serial: str, debug_actions: Optional[bool] = None, console_debug: bool = False) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    results = DailyRunner(context).run_all(load_run_all_task_order())
    failed = False
    for result in results:
        print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)")
        if result.message:
            print(f"  {result.message}")
        if result.state.value == "failed":
            failed = True
    return 1 if failed else 0


def cmd_probe_guild_dungeon_target(
    serial: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    task = TASK_CLASSES["guild_dungeon"](context)
    message = task.probe_target_from_current_map(tap_challenge=True)
    print(message)
    for record in getattr(task, "last_probe_records", ()):
        print(_format_guild_dungeon_probe_record(record))
    summary_path = getattr(task, "last_probe_summary_path", None)
    if summary_path is not None:
        print(f"summary={summary_path}")
    return 0


def _format_guild_dungeon_probe_record(record) -> str:
    selected = record.selected_center if record.selected_center is not None else "none"
    return (
        f"scan={record.scan_index:02d} node={record.node_kind} "
        f"node_center={record.node_center} node_conf={record.node_confidence:.4f} "
        f"remaining={record.remaining_count} challenge={record.challenge_count} bonus={record.bonus_count} "
        f"selected={selected} selected_conf={record.selected_confidence:.4f}"
    )


def cmd_probe_abyss_rental_scan(
    serial: str,
    debug_actions: Optional[bool] = None,
    console_debug: bool = False,
) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    rows = TASK_CLASSES["abyss"](context).probe_rental_scan(tap_forest=True)
    for row in rows:
        print(_format_abyss_rental_row(row))
    return 0


def _format_abyss_rental_row(row) -> str:
    power = row.power_text or "?"
    crop_path = Path(row.crop_path)
    file_name = crop_path.name
    parent_name = crop_path.parent.name
    display_path = str(Path(parent_name) / file_name) if parent_name else file_name
    return (
        f"scan={row.scan_index:02d} row={row.row_index} "
        f"power=<{power}> ocr_conf={row.confidence:.4f} rent_conf={row.rent_confidence:.4f} "
        f"rent_bright={_format_optional_float(row.rent_brightness_ratio)} "
        f"file={display_path}"
    )


def _format_optional_float(value) -> str:
    return "-" if value is None else f"{value:.4f}"


def cmd_run_tested_daily(serial: str, debug_actions: Optional[bool] = None, console_debug: bool = False) -> int:
    context = build_context(serial, debug=debug_actions, console_debug=console_debug)
    if not context.controller.connect():
        raise ConfigurationError(f"Cannot connect to ADB device: {serial}")
    context.controller.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    runner = DailyRunner(context)
    for task_key in TESTED_DAILY_TASK_ORDER:
        result = runner.run_task(task_key)
        print(f"{result.task_key}: {result.state.value} ({result.elapsed_seconds:.1f}s)", flush=True)
        if result.message:
            print(f"  {result.message}", flush=True)
        if result.state.value in ("failed", "needs_assets"):
            print(f"stopped_after={result.task_key}", flush=True)
            return 1
    return 0


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
            return cmd_go_daily(args.serial, args.debug_actions, args.debug)
        if args.command == "list-tasks":
            return cmd_list_tasks()
        if args.command == "probe-task":
            return cmd_probe_task(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "probe-current-task":
            return cmd_probe_current_task(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "probe-task-go-first":
            return cmd_probe_task_go_first(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "probe-current-task-go-first":
            return cmd_probe_current_task_go_first(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "run-task":
            return cmd_run_task(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "run-task-go-first":
            return cmd_run_task_go_first(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "run-current-task":
            return cmd_run_current_task(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "run-current-scene-task":
            return cmd_run_current_scene_task(args.serial, args.task, args.debug_actions, args.debug)
        if args.command == "run-tested-daily":
            return cmd_run_tested_daily(args.serial, args.debug_actions, args.debug)
        if args.command == "run-all":
            return cmd_run_all(args.serial, args.debug_actions, args.debug)
        if args.command == "probe-guild-dungeon-target":
            return cmd_probe_guild_dungeon_target(args.serial, args.debug_actions, args.debug)
        if args.command == "probe-abyss-rental-scan":
            return cmd_probe_abyss_rental_scan(args.serial, args.debug_actions, args.debug)
        parser.error(f"Unknown command: {args.command}")
        return 2
    except (AdbControllerError, BotError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
