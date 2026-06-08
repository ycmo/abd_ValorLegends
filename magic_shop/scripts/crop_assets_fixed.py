import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.vision_matcher import read_image, write_image
from pathlib import Path

def crop_and_save(img, dest_path, center_x, center_y, size=60):
    half = size // 2
    cropped = img[center_y - half : center_y + half, center_x - half : center_x + half]
    write_image(Path(dest_path), cropped)
    print(f"Saved {dest_path}")

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    screenshots_dir = os.path.join(base_dir, 'manual_screenshots', '魔法商店')
    assets_dir = os.path.join(base_dir, 'magic_shop', 'assets')

    src1 = os.path.join(screenshots_dir, '001_要購買1.png')
    img1 = read_image(Path(src1))
    
    # Row 1: y=140. Row 2: y=290. Col 1: x=365. Col 2: x=520. Col 3: x=675. Col 4: x=830.
    
    # 1. 紫珠 800 (Row 1, Col 1)
    crop_and_save(img1, os.path.join(assets_dir, 'item_purple_bead.png'), 365, 140)
    
    # 2. 金牌 10 (Row 2, Col 3) -> 神器碎片
    crop_and_save(img1, os.path.join(assets_dir, 'item_gold_medal.png'), 675, 290)
    
    src2 = os.path.join(screenshots_dir, '001_要購買2.png')
    img2 = read_image(Path(src2))
    
    # In 001_要購買2.png, let's assume it has 競技場票5 and 英雄碎片30.
    # We will need to check where they are. 
    # For now, I will extract them from probe or just wait.
    # Actually, let's just extract Purple Bead and Gold Medal first to prove it works.

if __name__ == "__main__":
    main()
