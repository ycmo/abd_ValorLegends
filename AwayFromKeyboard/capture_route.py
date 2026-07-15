import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from src.adb_controller import DeviceController


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class SystemEnv:
    def prompt_user(self, msg: str) -> str:
        return input(msg)

    def create_controller(self, serial: str | None = None) -> DeviceController:
        return DeviceController(serial=serial)

    def write_screenshot(self, controller: DeviceController, out_file: Path) -> None:
        screen = controller.screenshot()
        ok, buf = cv2.imencode(".png", screen)
        if not ok:
            raise RuntimeError(f"failed to write screenshot: {out_file}")
        out_file.write_bytes(buf.tobytes())

    def open_mspaint(self, file_path: Path) -> None:
        try:
            print("Opening screenshot in mspaint...")
            subprocess.Popen(["mspaint", str(file_path)])
        except Exception as exc:
            print(f"[warn] failed to open mspaint: {exc}")


class RouteCapturer:
    def __init__(self, env=None):
        self.env = env or SystemEnv()

    def capture(
        self,
        route: str,
        tag: str,
        serial: str | None = None,
        base_dir: Path | None = None,
    ) -> bool:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent

        screenshots_dir = base_dir / "route_screenshots" / route
        out_file = screenshots_dir / f"{tag}.png"

        if out_file.exists():
            print(f"[warn] screenshot already exists: {out_file}")
            ans = self.env.prompt_user("Overwrite? (y/n): ").strip().lower()
            if ans != "y":
                print("Capture cancelled.")
                return False

        screenshots_dir.mkdir(parents=True, exist_ok=True)

        try:
            controller = self.env.create_controller(serial)
            if not controller.connect():
                print("[error] cannot connect to ADB device")
                return False
            self.env.write_screenshot(controller, out_file)

            print(f"[ok] screenshot saved: {out_file}")
            print("Crop/edit the image, then keep it as the route template.")
            self.env.open_mspaint(out_file)
            return True
        except Exception as exc:
            print(f"[error] capture failed: {exc}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description="AwayFromKeyboard route screenshot capture tool")
    parser.add_argument("--route", required=True, help="Route name")
    parser.add_argument("--tag", required=True, help="Screenshot filename without .png, for example 001_entry")
    parser.add_argument("--serial", default=None, help="ADB serial override; omitted means auto-detect")

    args = parser.parse_args()

    capturer = RouteCapturer()
    success = capturer.capture(args.route, args.tag, args.serial)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
