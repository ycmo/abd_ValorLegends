import subprocess
import sys
import os
import json
from typing import List, Tuple

def get_default_adb_target() -> str:
    default_target = "127.0.0.1:5555"
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        json_path = os.path.join(project_root, "data", "status_graph.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("device_config", {}).get("adb_target", default_target)
    except Exception:
        pass
    return default_target

ADB_TARGET = get_default_adb_target()

# Automatically connect to the local emulator on import to handle sandbox/session resets
try:
    subprocess.run(["adb", "connect", ADB_TARGET], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
except Exception as e:
    print(f"Warning: Auto-connection to emulator failed on import: {e}", file=sys.stderr)

class AdbError(Exception):
    pass

def run_adb_cmd(args: List[str]) -> subprocess.CompletedProcess:
    """
    Runs an ADB command using subprocess.
    If the command fails (return code != 0), prints the command, return code, and stderr,
    and raises an AdbError.
    """
    cmd = ["adb", "-s", ADB_TARGET] + args
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        if res.returncode != 0:
            print(f"Command: {' '.join(cmd)}", file=sys.stderr)
            print(f"Return Code: {res.returncode}", file=sys.stderr)
            print(f"Stderr:\n{res.stderr.strip()}", file=sys.stderr)
            raise AdbError(f"ADB command failed: {' '.join(cmd)} with exit code {res.returncode}")
        return res
    except FileNotFoundError:
        print(f"Command: {' '.join(cmd)}", file=sys.stderr)
        print("Return Code: -1", file=sys.stderr)
        print("Stderr: 'adb' command not found in system PATH.", file=sys.stderr)
        raise AdbError("adb command not found in system PATH")
    except Exception as e:
        print(f"Command: {' '.join(cmd)}", file=sys.stderr)
        print("Return Code: -1", file=sys.stderr)
        print(f"Stderr: Subprocess exception: {str(e)}", file=sys.stderr)
        raise

def get_devices() -> str:
    """
    Returns the output of 'adb devices'.
    """
    res = run_adb_cmd(["devices"])
    return res.stdout.strip()

def take_screenshot(output_path: str = "screenshots/current.png") -> Tuple[int, int, int]:
    """
    Takes a screenshot on the device and pulls it to the local system.
    Returns: (width, height, byte_size) of the saved file.
    """
    # Ensure directory exists
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    
    # 1. Capture screenshot on device
    run_adb_cmd(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
    
    # 2. Pull screenshot to local
    run_adb_cmd(["pull", "/sdcard/screenshot.png", output_path])
    
    # 3. Read image to get dimensions and byte size
    import cv2
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Pulled file not found: {output_path}")
        
    img = cv2.imread(output_path)
    if img is None:
        raise ValueError(f"Failed to read image using OpenCV: {output_path}")
        
    height, width, _ = img.shape
    byte_size = os.path.getsize(output_path)
    
    return width, height, byte_size

def tap_coordinate(x: int, y: int) -> None:
    """
    Sends a tap command to the device.
    """
    run_adb_cmd(["shell", "input", "tap", str(x), str(y)])
