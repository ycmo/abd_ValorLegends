import sys
from pathlib import Path

target_file = Path("E:/antigravity/adb_vl/switch_account/switch_account.py")
content = target_file.read_text(encoding="utf-8")

# 1. Imports
if "import cv2" not in content[:300]:
    content = content.replace("import json\n", "import json\nimport cv2\nimport numpy as np\nimport subprocess\n")

# 2. Add Helper
helper_str = """def save_and_show_debug(screen, debug_path: Path, center: tuple = None, roi: tuple = None):
    debug_screen = screen.copy()
    if center:
        cx, cy = center
        cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
        cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
        cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
    if roi:
        rx, ry, rw, rh = roi
        cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)

    ok, buf = cv2.imencode(".png", debug_screen)
    if ok:
        debug_path.write_bytes(buf.tobytes())
        print(f"📸 已儲存除錯截圖並開啟小畫家: {debug_path.name}")
        subprocess.Popen(["mspaint", str(debug_path.resolve())])

def wait_and_tap"""

content = content.replace("def wait_and_tap", helper_str)

# 3. Clean up wait_and_tap
# Remove imports at top of wait_and_tap
content = content.replace("    # 讀取一次 template，用來決定 ROI 與 Debug\n    import cv2\n    import numpy as np\n    temp_img", "    # 讀取一次 template，用來決定 ROI 與 Debug\n    temp_img")

# First block in wait_and_tap
block_1 = """                try:
                    import cv2
                    import subprocess
                    debug_screen = screen.copy()
                    
                    cx, cy = res.center
                    cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
                    cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
                    cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
                    
                    if roi:
                        rx, ry, rw, rh = roi
                        cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)
                        
                    debug_path = DEBUG_DIR / f"stuck_debug_{template_name}"
                    ok, buf = cv2.imencode(".png", debug_screen)
                    if ok:
                        debug_path.write_bytes(buf.tobytes())
                        print(f"📸 儲存未跳轉除錯截圖並開啟小畫家: {debug_path.name}")
                        subprocess.Popen(["mspaint", str(debug_path.resolve())])
                        raise RuntimeError(f"異常卡死：已點擊 3 次仍未跳轉，開啟小畫家除錯 ({debug_path.name})")
                except Exception as e:
                    if isinstance(e, RuntimeError): raise e
                    print(f"除錯截圖處理失敗: {e}")"""

rep_1 = """                try:
                    debug_path = DEBUG_DIR / f"stuck_debug_{template_name}"
                    save_and_show_debug(screen, debug_path, center=res.center, roi=roi)
                    raise RuntimeError(f"異常卡死：已點擊 3 次仍未跳轉，開啟小畫家除錯 ({debug_path.name})")
                except Exception as e:
                    if isinstance(e, RuntimeError): raise e
                    print(f"除錯截圖處理失敗: {e}")"""

content = content.replace(block_1, rep_1)

# Second block in wait_and_tap
block_2 = """        try:
            import cv2
            import subprocess
            debug_screen = controller.screenshot()
            
            if fallback_coord:
                cx, cy = fallback_coord
                # 畫紅色圓圈和十字標記
                cv2.circle(debug_screen, (cx, cy), 20, (0, 0, 255), 3)
                cv2.line(debug_screen, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
                cv2.line(debug_screen, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
                
                if roi:
                    rx, ry, rw, rh = roi
                    # 畫綠色矩形來顯示尋找範圍 (ROI)
                    cv2.rectangle(debug_screen, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 3)
                    
                debug_path = DEBUG_DIR / f"error_debug_{template_name}"
                ok, buf = cv2.imencode(".png", debug_screen)
                if ok:
                    debug_path.write_bytes(buf.tobytes())
                    print(f"📸 已儲存除錯截圖並開啟小畫家: {debug_path.name}")
                    subprocess.Popen(["mspaint", str(debug_path.resolve())])
                    raise RuntimeError(f"超時未找到目標，已開啟小畫家除錯 ({debug_path.name})")
        except Exception as e:
            if isinstance(e, RuntimeError): raise e
            print(f"除錯截圖處理失敗: {e}")"""

rep_2 = """        try:
            debug_screen = controller.screenshot()
            debug_path = DEBUG_DIR / f"error_debug_{template_name}"
            save_and_show_debug(debug_screen, debug_path, center=fallback_coord, roi=roi)
            raise RuntimeError(f"超時未找到目標，已開啟小畫家除錯 ({debug_path.name})")
        except Exception as e:
            if isinstance(e, RuntimeError): raise e
            print(f"除錯截圖處理失敗: {e}")"""

content = content.replace(block_2, rep_2)

# Remove imports in wait_for_appearance
content = content.replace("    template_path = TEMPLATES_DIR / template_name\n    import cv2\n    import numpy as np\n    temp_img", "    template_path = TEMPLATES_DIR / template_name\n    temp_img")


# Third block in select_server
block_3 = """        # 截圖除錯
        import cv2
        import subprocess
        debug_path = DEBUG_DIR / f"debug_server_{server_name}.png"
        x, y, w, h = roi_box
        cv2.rectangle(screen, (x, y), (x + w, y + h), (0, 255, 0), 2)
        ok, buf = cv2.imencode(".png", screen)
        if ok:
            debug_path.write_bytes(buf.tobytes())
            print(f"📸 找不到 {server_name}，已儲存除錯截圖並開啟小畫家: {debug_path.name}")
            subprocess.Popen(["mspaint", str(debug_path.resolve())])
        raise RuntimeError(f"找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")"""

rep_3 = """        # 截圖除錯
        debug_path = DEBUG_DIR / f"debug_server_{server_name}.png"
        save_and_show_debug(screen, debug_path, roi=roi_box)
        raise RuntimeError(f"找不到任何符合 {server_name} 的圖片，開啟小畫家除錯！")"""

content = content.replace(block_3, rep_3)

# Fourth block in switch_account
block_4 = """        try:
            import cv2
            import subprocess
            debug_screen = controller.screenshot()
            debug_path = TEMPLATES_DIR.parent / "error_debug_timeout_10loops.png"
            ok, buf = cv2.imencode(".png", debug_screen)
            if ok:
                debug_path.write_bytes(buf.tobytes())
                print(f"📸 已儲存超時除錯截圖並開啟小畫家: {debug_path.name}")
                subprocess.Popen(["mspaint", str(debug_path.resolve())])
        except Exception as e:
            print(f"除錯截圖處理失敗: {e}")"""

rep_4 = """        try:
            debug_screen = controller.screenshot()
            debug_path = TEMPLATES_DIR.parent / "error_debug_timeout_10loops.png"
            save_and_show_debug(debug_screen, debug_path)
        except Exception as e:
            print(f"除錯截圖處理失敗: {e}")"""

content = content.replace(block_4, rep_4)


target_file.write_text(content, encoding="utf-8")
print("Refactoring complete.")
