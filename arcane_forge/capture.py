import argparse
import sys
from pathlib import Path

from src.adb_controller import DeviceController
from src.paint_cropper import run_paint_crop_workflow


def get_unique_screenshot_path(output_dir: Path, base_name: str) -> Path:
    if base_name.endswith('.png'):
        base_name = base_name[:-4]

    screenshot_path = output_dir / f"{base_name}.png"
    if not screenshot_path.exists():
        return screenshot_path

    index = 2
    while True:
        screenshot_path = output_dir / f"{base_name}_{index}.png"
        if not screenshot_path.exists():
            return screenshot_path
        index += 1

def capture_and_crop(filename: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = get_unique_screenshot_path(output_dir, filename)

    print(f"Connecting to ADB and taking screenshot: {screenshot_path}")
    ctrl = DeviceController()
    ctrl.connect()
    ctrl.save_screenshot(screenshot_path)

    print("Screenshot saved. Starting paint cropping workflow...")
    # run_paint_crop_workflow預設會將檔案存放在 screenshot_path.parent，也就是 output_dir
    saved_crops = run_paint_crop_workflow(screenshot_path)

    print("\nWorkflow complete. Saved files:")
    print(f" - Original Screenshot: {screenshot_path}")
    for crop in saved_crops:
        print(f" - Cropped Template: {crop}")

def main():
    parser = argparse.ArgumentParser(description="Capture screenshot and crop templates for Arcane Forge")
    parser.add_argument("filename", help="Base filename for the screenshot (without extension)")
    args = parser.parse_args()

    # 指定單一輸出目錄
    output_dir = Path("arcane_forge/assets/manual")
    try:
        capture_and_crop(args.filename, output_dir)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
