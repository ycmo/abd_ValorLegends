import time
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.adb_controller import DeviceController
from src.config import DEFAULT_SERIAL

from src.vision_matcher import write_image

def main():
    print("Connecting to device...")
    device = DeviceController(DEFAULT_SERIAL)
    
    print("Tapping Arena Ticket 5 price button at (520, 260)...")
    device.tap(520, 260)
    
    print("Waiting 2 seconds...")
    time.sleep(2)
    
    print("Taking screenshot...")
    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'debug_output', 'after_tap.png'))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    from pathlib import Path
    img = device.screenshot()
    write_image(Path(output_path), img)
    print(f"Screenshot saved to {output_path}")

if __name__ == "__main__":
    main()
