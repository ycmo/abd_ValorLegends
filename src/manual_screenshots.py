from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from src.adb_controller import AdbControllerError, DeviceController
from src.config import DEFAULT_SERIAL, MANUAL_SCREENSHOTS_DIR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a manual reference screenshot")
    parser.add_argument("--task", required=True, help="Task folder name, e.g. 無盡試煉")
    parser.add_argument("--index", required=True, help="Screenshot index, e.g. 1 or 001")
    parser.add_argument("--scene", help="Scene name, e.g. 每日任務")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, help=f"ADB serial, default: {DEFAULT_SERIAL}")
    parser.add_argument("--open-paint", action="store_true", help="Open saved image in mspaint (default)")
    parser.add_argument("--no-open-paint", action="store_true", help="Do not open saved image in mspaint")
    return parser


def main(argv: list = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        index = f"{int(args.index):03d}"
    except ValueError:
        print(f"ERROR: --index must be an integer: {args.index}", file=sys.stderr)
        return 2

    filename = f"{index}_{args.scene}.png" if args.scene else f"{index}.png"
    output_path = MANUAL_SCREENSHOTS_DIR / args.task / filename
    if output_path.exists():
        print(f"ERROR: file already exists, refusing to overwrite: {output_path}", file=sys.stderr)
        return 1

    controller = DeviceController(args.serial)
    if not controller.connect():
        print(f"ERROR: cannot connect to ADB device: {args.serial}", file=sys.stderr)
        return 1

    try:
        image = controller.screenshot()
    except AdbControllerError as exc:
        print(f"ERROR: screenshot failed: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        print("ERROR: cv2.imencode failed", file=sys.stderr)
        return 1
    output_path.write_bytes(buf.tobytes())

    height, width = image.shape[:2]
    print(f"saved {output_path.relative_to(MANUAL_SCREENSHOTS_DIR.parent)}")
    print(f"{width}/{height}")
    print(output_path.stat().st_size)

    if not args.no_open_paint:
        open_in_paint(output_path)
    return 0


def open_in_paint(path: Path) -> None:
    subprocess.Popen(["mspaint", str(path.resolve())])


if __name__ == "__main__":
    raise SystemExit(main())
