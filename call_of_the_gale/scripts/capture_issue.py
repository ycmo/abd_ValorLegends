import sys
from pathlib import Path
import time
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.adb_controller import DeviceController

def main():
    print("Connecting to ADB device...")
    controller = DeviceController()
    if not controller.connect():
        print("Failed to connect to device.")
        return

    capture_dir = Path(__file__).resolve().parents[1] / "runtime_captures"
    capture_dir.mkdir(exist_ok=True)
    
    # We use a fixed name 'issue.png' as requested in CODEX_NOTES
    out_path = capture_dir / "issue.png"
    
    print(f"Taking screenshot to {out_path}...")
    try:
        controller.save_screenshot(out_path)
    except Exception as e:
        print(f"Failed to capture screenshot: {e}")
        return

    print("Screenshot saved. The user will open MS Paint to inspect it.")

if __name__ == "__main__":
    main()
