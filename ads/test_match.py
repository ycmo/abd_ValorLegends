import cv2
import os
import sys
import numpy as np
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from vision_matcher import VisionMatcher

def main():
    screen_path = os.path.join(_THIS_DIR, "captures", "test_screen_20260605_071116.png")
    template_path = Path(os.path.join(_THIS_DIR, "assets", "entry", "btn_free_ad.png"))
    
    screen_data = np.fromfile(screen_path, dtype=np.uint8)
    screen = cv2.imdecode(screen_data, cv2.IMREAD_COLOR)
    
    matcher = VisionMatcher(threshold=0.1) # extremely low threshold to see best match
    res = matcher.match_template(screen, template_path, threshold=0.1)
    
    if res:
        print(f"Max Confidence: {res.confidence:.4f} at {res.center}")
    else:
        print("No match at all!")

if __name__ == "__main__":
    main()
