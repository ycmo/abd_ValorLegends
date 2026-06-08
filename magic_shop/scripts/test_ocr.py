import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.vision_matcher import read_image
from src.ocr_utils import recognize_text

def test_ocr():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    img_path = os.path.join(base_dir, 'captures', 'magic_shop_probe.png')
    img = read_image(Path(img_path))
    
    # Coordinates for gold amount
    gold_img = img[15:45, 730:805]
    
    text = recognize_text(gold_img)
    print(f"Raw OCR text: '{text}'")
    
    clean_text = text.replace('k', '').replace('K', '').replace(',', '').replace('.', '').strip()
    try:
        val = int(clean_text)
        print(f"Parsed gold: {val}")
    except ValueError:
        print("Failed to parse gold.")

if __name__ == "__main__":
    test_ocr()
