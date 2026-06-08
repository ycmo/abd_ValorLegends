import cv2
import numpy as np
import os
from pathlib import Path

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    src_path = os.path.join(base_dir, 'manual_screenshots', '魔法商店', '001_要購買1.png')
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
    from src.vision_matcher import read_image, write_image
    
    img = read_image(Path(src_path))
    
    # Draw horizontal and vertical lines every 50 pixels
    for y in range(0, img.shape[0], 50):
        cv2.line(img, (0, y), (img.shape[1], y), (0, 255, 0), 1)
        cv2.putText(img, str(y), (10, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
    for x in range(0, img.shape[1], 50):
        cv2.line(img, (x, 0), (x, img.shape[0]), (0, 255, 0), 1)
        cv2.putText(img, str(x), (x + 5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    dest_path = os.path.join(base_dir, 'magic_shop', 'debug_output', 'grid.png')
    write_image(Path(dest_path), img)
    print(f"Saved grid image to {dest_path}")

if __name__ == "__main__":
    main()
