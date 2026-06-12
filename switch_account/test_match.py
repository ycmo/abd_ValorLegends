import cv2
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.vision_matcher import VisionMatcher

def run_tests():
    matcher = VisionMatcher()
    templates_dir = Path(r"E:\antigravity\adb_vl\switch_account\templates")
    screenshots_dir = Path(r"E:\antigravity\adb_vl\manual_screenshots\帳號切換")
    
    print("=== 開始本地單元測試 ===")
    
    all_pass = True
    for t_path in sorted(templates_dir.glob("*.png")):
        base_name = t_path.stem.rsplit('_', 1)[0]
        orig_path = screenshots_dir / f"{base_name}.png"
        
        if not orig_path.exists():
            print(f"⚠️ 跳過 {t_path.name}: 找不到對應的原圖 {orig_path.name}")
            continue
            
        orig = cv2.imdecode(np.fromfile(str(orig_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        template = cv2.imdecode(np.fromfile(str(t_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        
        if orig is None or template is None:
            continue
            
        result = cv2.matchTemplate(orig, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        
        status = "[PASS]" if max_val >= 0.95 else "[FAIL]"
        if max_val < 0.95:
            all_pass = False
            
        print(f"{status} | Template: {t_path.name:25s} | Confidence: {max_val:.4f} | Coord: {max_loc}")
        
    print("========================")
    if all_pass:
        print("[SUCCESS] All templates match their original screenshots perfectly!")
    else:
        print("[WARNING] Some templates failed to match with high confidence.")

if __name__ == "__main__":
    run_tests()
