import cv2

img_path = r"E:\antigravity\adb_vl\switch_account\debug_logs\debug_server_em3.png"
out_path = r"E:\antigravity\adb_vl\switch_account\ROI_preview.png"

img = cv2.imread(img_path)
if img is not None:
    x, y, w, h = 329, 36, 627, 162
    cv2.rectangle(img, (x, y), (x+w, y+h), (0, 0, 255), 3) # Red box
    cv2.imwrite(out_path, img)
    print(f"Saved ROI preview to {out_path}")
else:
    print("Could not read image!")
