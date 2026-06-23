import sys
import cv2
import numpy as np
from pathlib import Path

def relax_red_mask(image):
    blue, green, red = cv2.split(image)
    strongest_other = np.maximum(blue, green).astype(np.int16)
    red_i = red.astype(np.int16)
    
    # Relaxed mask: red is dominant by at least 30
    mask = (
        (red >= 100)
        & ((red_i - strongest_other) >= 30)
    )
    return mask.astype(np.uint8) * 255

def extract():
    src_path = list(Path('switch_account/debug').glob('*.png'))[0]
    dst_path = Path('switch_account/templates/009_關閉廣告_0.png')
    
    img = cv2.imdecode(np.fromfile(str(src_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    
    mask = relax_red_mask(img)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    found = False
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 10 or h < 10:
            continue
        area = w * h
        if area < 100 or area > img.shape[0]*img.shape[1]*0.9:
            continue
            
        # If it looks like a manual drawn box, just take it
        print(f"Found red contour at: x={x}, y={y}, w={w}, h={h}")
        # Crop inner area (assume border is ~2-4 pixels)
        # We will crop 4 pixels inward to remove the red stroke
        y_min = y + 4
        y_max = y + h - 4
        x_min = x + 4
        x_max = x + w - 4
        if y_max <= y_min or x_max <= x_min:
            continue
            
        crop = img[y_min:y_max, x_min:x_max]
        ok, buf = cv2.imencode(".png", crop)
        if ok:
            dst_path.write_bytes(buf.tobytes())
            print(f"Extracted to {dst_path.name}")
            found = True
            break
            
    if not found:
        print("Still no red boxes found with relaxed constraints.")

if __name__ == '__main__':
    extract()
