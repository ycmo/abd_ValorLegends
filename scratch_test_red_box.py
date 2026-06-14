import cv2
import numpy as np
from pathlib import Path

def find_diff_colors(orig_path, edit_path):
    orig = cv2.imdecode(np.fromfile(str(orig_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    edit = cv2.imdecode(np.fromfile(str(edit_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    
    diff = cv2.absdiff(orig, edit)
    mask = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) > 10
    mask = mask.astype(np.uint8) * 255
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"--- Diff Analysis for {Path(edit_path).name} ---")
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h > 50:
            print(f"User Edit Bounding Box: x={x}, y={y}, w={w}, h={h}, area={w*h}")

find_diff_colors(r"E:\antigravity\adb_vl\ads2\assets\2_communication\manual_rescue_20260613_145759_original.png", r"E:\antigravity\adb_vl\ads2\assets\2_communication\manual_rescue_20260613_145759_edit.png")
find_diff_colors(r"E:\antigravity\adb_vl\ads2\assets\2_communication\manual_rescue_20260613_145852_original.png", r"E:\antigravity\adb_vl\ads2\assets\2_communication\manual_rescue_20260613_145852_edit.png")

