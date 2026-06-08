import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.vision_matcher import read_image, write_image
from pathlib import Path

def crop_and_save(src_path, dest_path, x, y, w, h):
    img = read_image(Path(src_path))
    if img is None:
        print(f"Error loading {src_path}")
        return
    cropped = img[y:y+h, x:x+w]
    write_image(Path(dest_path), cropped)
    print(f"Saved {dest_path}")

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    screenshots_dir = os.path.join(base_dir, 'manual_screenshots', '魔法商店')
    assets_dir = os.path.join(base_dir, 'magic_shop', 'assets')

    # coordinates: x, y, w, h
    # 001_要購買1.png
    src1 = os.path.join(screenshots_dir, '001_要購買1.png')
    crop_and_save(src1, os.path.join(assets_dir, 'item_purple_bead.png'), 335, 260, 60, 60) # purple bead icon
    crop_and_save(src1, os.path.join(assets_dir, 'item_gold_medal.png'), 645, 260, 60, 60) # gold medal icon
    
    # 001_要購買2.png
    src2 = os.path.join(screenshots_dir, '001_要購買2.png')
    crop_and_save(src2, os.path.join(assets_dir, 'item_arena_ticket.png'), 490, 120, 60, 60) # arena ticket
    crop_and_save(src2, os.path.join(assets_dir, 'item_hero_shard.png'), 490, 310, 60, 60) # hero shard
    
    # 003_購買確認.png
    src3 = os.path.join(screenshots_dir, '003_購買確認.png')
    crop_and_save(src3, os.path.join(assets_dir, 'buy_confirm_btn.png'), 420, 370, 120, 40) # buy confirm button
    
    # Refresh button (100)
    crop_and_save(src1, os.path.join(assets_dir, 'refresh_100.png'), 760, 50, 140, 40) 

if __name__ == "__main__":
    main()
