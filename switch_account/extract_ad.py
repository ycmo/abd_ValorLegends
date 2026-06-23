import sys
import cv2
from pathlib import Path

sys.path.insert(0, '.')
from src.vision_matcher import read_image, write_image
from src.paint_cropper import find_red_boxes, crop_inside_colored_box

def extract():
    src_path = list(Path('switch_account/debug').glob('*.png'))[0]
    dst_path = Path('switch_account/templates/009_關閉廣告_0.png')
    
    if not src_path.exists():
        print(f"File not found: {src_path}")
        return
        
    img = read_image(src_path, cv2.IMREAD_COLOR)
    boxes = find_red_boxes(img)
    
    if boxes:
        print(f"Found {len(boxes)} red boxes.")
        crop = crop_inside_colored_box(img, boxes[0], 'red')
        write_image(dst_path, crop)
        print(f'Template extracted successfully to {dst_path.name}')
    else:
        print('No red boxes found in the image!')

if __name__ == '__main__':
    extract()
