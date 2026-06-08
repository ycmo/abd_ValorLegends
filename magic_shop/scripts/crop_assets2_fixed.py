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

    src2 = os.path.join(screenshots_dir, '001_要購買2.png')
    img2 = read_image(Path(src2))
    
    # 3. 競技場票 5 (Row 1, Col 2)
    crop_and_save(img2, os.path.join(assets_dir, 'item_arena_ticket.png'), 520, 140)
    
    # 4. 英雄碎片 30 (Row 2, Col 2) -> 史詩英雄碎片
    crop_and_save(img2, os.path.join(assets_dir, 'item_hero_shard.png'), 520, 290)

if __name__ == "__main__":
    main()
