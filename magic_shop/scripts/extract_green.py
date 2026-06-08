import sys
import os
import cv2
import numpy as np
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.vision_matcher import read_image, write_image
from pathlib import Path

def extract_green_boxes(img_path, output_dir, prefix):
    img = read_image(Path(img_path))
    if img is None:
        return
    
    # Define pure green color range
    lower_green = np.array([0, 200, 0])
    upper_green = np.array([50, 255, 50])
    
    mask = cv2.inRange(img, lower_green, upper_green)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    idx = 1
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # Filter small noise
        if w > 50 and h > 50:
            # The box is around the item. The item icon is in the upper part of the box.
            # Let's just crop a 60x60 patch from the center top of the box
            center_x = x + w // 2
            center_y = y + h // 2 - 30 # Slightly above center to get the icon, not the text
            
            # Or better, just crop 60x60 around center_x, center_y
            half = 30
            icon_crop = img[center_y - half: center_y + half, center_x - half: center_x + half]
            
            out_path = os.path.join(output_dir, f"{prefix}_{idx}.png")
            write_image(Path(out_path), icon_crop)
            print(f"Extracted {prefix}_{idx}.png at {center_x}, {center_y} from {os.path.basename(img_path)}")
            idx += 1

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    screenshots_dir = os.path.join(base_dir, 'manual_screenshots', '魔法商店')
    assets_dir = os.path.join(base_dir, 'magic_shop', 'debug_output')
    os.makedirs(assets_dir, exist_ok=True)
    
    src1 = os.path.join(screenshots_dir, '001_要購買1.png')
    src2 = os.path.join(screenshots_dir, '001_要購買2.png')
    
    extract_green_boxes(src1, assets_dir, "auto_crop_1")
    extract_green_boxes(src2, assets_dir, "auto_crop_2")

if __name__ == "__main__":
    main()
