import os
import cv2
from src.vision_matcher import read_image
from src.ocr_utils import get_cached_easyocr_reader, read_texts_easyocr

# Initialize OCR
reader = get_cached_easyocr_reader(("en",))

# Read test image
image_path = r"arcane_forge/assets/manual/升星2.png"
if not os.path.exists(image_path):
    print(f"File not found: {image_path}")
    exit(1)

screen = read_image(image_path, cv2.IMREAD_COLOR)

roi = (500, 110, 100, 40)
ocr_results = read_texts_easyocr(screen, roi=roi, reader=reader, allowlist="0123456789,")

dust_amount = -1
if ocr_results:
    best_match = max(ocr_results, key=lambda x: x['confidence'])
    clean_text = best_match['text'].replace(',', '')
    try:
        dust_amount = int(clean_text)
    except ValueError:
        pass

print(f"Extracted dust_amount: {dust_amount}")
