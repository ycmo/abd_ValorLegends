import cv2
import numpy as np
from pathlib import Path

source_path = Path(r"E:\antigravity\adb_vl\manual_screenshots\帳號切換\008_1_確認切換伺服器.png")
target_path = Path(r"E:\antigravity\adb_vl\switch_account\templates\008_1_確認切換是_0.png")

if not source_path.exists():
    print(f"Source image not found: {source_path}")
    exit(1)

img_array = np.fromfile(str(source_path), np.uint8)
img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
if img is None:
    print("Could not read image")
    exit(1)

# Find red box
lower_red = np.array([0, 0, 200])
upper_red = np.array([50, 50, 255])
mask = cv2.inRange(img, lower_red, upper_red)

coords = cv2.findNonZero(mask)
if coords is not None:
    x, y, w, h = cv2.boundingRect(coords)
    print(f"Red box found at ROI: x={x}, y={y}, w={w}, h={h}")
    # Remove the red border itself by shrinking the bounding box by 2 pixels on each side
    crop_img = img[y+2:y+h-2, x+2:x+w-2]
    
    if crop_img.size > 0:
        ok, buf = cv2.imencode(".png", crop_img)
        if ok:
            target_path.write_bytes(buf.tobytes())
            print(f"Successfully cropped and saved to {target_path}")
    else:
        print("Cropped image is empty.")
else:
    print("No red box found.")
