import cv2
from pathlib import Path
import os
import shutil

debug_dir = Path(r'E:\antigravity\adb_vl\magic_shop\debug_output')
# Find the latest debug image
latest_img = max(debug_dir.glob('dry_run_ocr_*.png'), key=lambda f: f.stat().st_mtime)

# Read the image
img = cv2.imread(str(latest_img))

# Draw the OCR ROI (x=250, y=100, w=710, h=440) -> bottom right is (960, 540)
cv2.rectangle(img, (250, 100), (960, 540), (0, 0, 255), 4)

# Add text to explain
cv2.putText(img, "OCR ROI (250, 100) to (960, 540)", (260, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

# Save to artifacts directory
artifact_dir = Path(r'C:\Users\USER\.gemini\antigravity-cli\brain\e8c7a13c-9261-4ce6-bd1f-7573b51bf487')
output_path = artifact_dir / 'ocr_roi_demo.png'

cv2.imwrite(str(output_path), img)
print(f"Saved OCR ROI demo to {output_path}")
