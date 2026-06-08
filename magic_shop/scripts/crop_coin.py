import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.vision_matcher import read_image, write_image
from pathlib import Path

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    screenshots_dir = os.path.join(base_dir, 'manual_screenshots', '魔法商店')
    assets_dir = os.path.join(base_dir, 'magic_shop', 'assets')

    src = os.path.join(screenshots_dir, '001_要購買1.png')
    img = read_image(Path(src))
    
    # Gold coin in the price button of the first item
    # Item 1 price button is around 310-380 x, 350-390 y.
    # The coin is at the left of the price text.
    # In 001_要購買1.png, purple bead 960k. The coin is at x=315 to 335, y=360 to 380.
    coin_cropped = img[360:385, 315:345]
    dest = os.path.join(assets_dir, 'gold_coin.png')
    write_image(Path(dest), coin_cropped)
    print("Saved gold_coin.png")

if __name__ == "__main__":
    main()
