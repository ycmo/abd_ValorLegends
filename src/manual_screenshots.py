import argparse
import sys
import os
import subprocess
from pathlib import Path
import cv2

# Set stdout/stderr encoding to utf-8 to correctly print Chinese characters in terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Ensure we can import adb_controller from the same src/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adb_controller import DeviceController, AdbControllerError
from adb_client import get_default_adb_target

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual Screenshot CLI without game logic"
    )
    parser.add_argument(
        "--task",
        required=True,
        help="Task name, e.g. 無盡試煉"
    )
    parser.add_argument(
        "--index",
        required=True,
        help="Screenshot index, e.g. 1, 01, 001. Will be formatted to 3 digits."
    )
    parser.add_argument(
        "--scene",
        help="Scene name, optional, e.g. 每日任務"
    )
    parser.add_argument(
        "--open-paint",
        action="store_true",
        help="Open screenshot in mspaint after saving"
    )
    
    default_serial = get_default_adb_target()
    parser.add_argument(
        "--serial",
        default=default_serial,
        help=f"ADB device serial, default: {default_serial}"
    )

    args = parser.parse_args()

    # 1. Format index to 3 digits
    try:
        index_val = int(args.index)
        index_str = f"{index_val:03d}"
    except ValueError:
        print(f"Error: index must be an integer, got '{args.index}'", file=sys.stderr)
        sys.exit(1)

    # 2. Setup path
    task_dir = Path("manual_screenshots") / args.task
    if args.scene:
        filename = f"{index_str}_{args.scene}.png"
    else:
        filename = f"{index_str}.png"
    
    output_path = task_dir / filename
    
    if output_path.exists():
        print(f"Warning: File already exists at {output_path}. Aborting to prevent overwrite.", file=sys.stderr)
        sys.exit(1)

    # 3. Connect to Device
    print(f"Connecting to ADB device: {args.serial}...")
    controller = DeviceController(serial=args.serial)
    if not controller.connect():
        print(f"Error: Failed to connect to ADB device '{args.serial}'", file=sys.stderr)
        sys.exit(1)

    # 4. Take screenshot
    print("Capturing screenshot via ADB...")
    try:
        img = controller.screenshot()
    except AdbControllerError as e:
        print(f"Error during screenshot capture: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during screenshot capture: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Save the image
    try:
        task_dir.mkdir(parents=True, exist_ok=True)
        # cv2.imwrite handles unicode paths in Python if we use imencode or if cv2.imwrite supports it on this environment.
        # To be safe with Chinese characters in paths on Windows:
        # cv2.imencode returns (retval, buf). Then we write buf to the file.
        success, buf = cv2.imencode(".png", img)
        if not success:
            raise IOError("cv2.imencode failed to convert image to PNG format")
        output_path.write_bytes(buf.tobytes())
    except Exception as e:
        print(f"Error saving screenshot file: {e}", file=sys.stderr)
        sys.exit(1)

    # 6. Retrieve dimensions and size
    try:
        height, width, _ = img.shape
        byte_size = output_path.stat().st_size
    except Exception as e:
        print(f"Error retrieving saved file metadata: {e}", file=sys.stderr)
        sys.exit(1)

    # Output success information
    # Print paths with forward slashes for cross-platform/clean representation or as defined
    relative_path_str = f"manual_screenshots/{args.task}/{filename}"
    print(f"saved {relative_path_str}")
    print(f"{width}/{height}")
    print(f"{byte_size}")

    # 7. Optional Open Paint
    if args.open_paint:
        print(f"Opening {output_path} with mspaint...")
        try:
            # Open mspaint asynchronously
            subprocess.Popen(["mspaint", str(output_path.resolve())])
        except Exception as e:
            print(f"Warning: Failed to open mspaint: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
