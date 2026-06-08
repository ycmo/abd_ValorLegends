import cv2
import easyocr
from pathlib import Path
import numpy as np

print('Loading EasyOCR...')
reader = easyocr.Reader(['en'])
debug_dir = Path(r'E:\antigravity\adb_vl\magic_shop\debug_output')
latest_img = max(debug_dir.glob('dry_run_ocr_960k_*.png'), key=lambda f: f.stat().st_mtime)
print(f'Testing on {latest_img.name}...')
img = cv2.imdecode(np.fromfile(str(latest_img), dtype=np.uint8), cv2.IMREAD_COLOR)

roi = img[100:440, 250:960]

configs = [
    ('mag_ratio=2.0', {'mag_ratio': 2.0}),
    ('mag_ratio=3.0', {'mag_ratio': 3.0}),
    ('mag_ratio=2.0, adjust_contrast=True', {'mag_ratio': 2.0, 'adjust_contrast': True}),
    ('Grayscale, mag_ratio=3.0', {'mag_ratio': 3.0, 'is_gray': True})
]

for name, kwargs in configs:
    test_img = roi
    if kwargs.get('is_gray'):
        test_img = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        del kwargs['is_gray']

    print(f'\n--- Config: {name} ---')
    results = reader.readtext(test_img, allowlist='0123456789km,', **kwargs)
    for box, text, conf in results:
        if '5' in text or '0' in text:
            print(f'Found: {text} (Conf: {conf:.3f})')
