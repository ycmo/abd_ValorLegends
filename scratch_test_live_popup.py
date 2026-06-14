import cv2
from pathlib import Path
from src.vision_matcher import VisionMatcher
from src.adb_controller import DeviceController

def main():
    base_dir = Path(r"E:\antigravity\adb_vl")
    template_path = base_dir / "switch_account" / "templates" / "008_1_確認切換是_0.png"
    out_path = base_dir / "switch_account" / "debug" / "stuck_screen.png"
    
    devices = DeviceController.list_devices()
    if not devices:
        print("找不到設備")
        return
        
    controller = DeviceController(devices[0])
    print("正在擷取當前卡住的畫面...")
    screen = controller.screenshot()
    
    # 存檔以供除錯
    cv2.imwrite(str(out_path), screen)
    print(f"畫面已儲存至 {out_path}")
    
    matcher = VisionMatcher()
    
    res = matcher.match_template(screen, template_path, threshold=0.1, check_brightness=False)
    
    if res:
        print(f"【即時畫面比對結果】")
        print(f"找到最像的位置！信心度: {res.confidence:.4f}, 座標: {res.center}")
        # 在圖上畫框
        x, y, w, h = res.bbox
        cv2.rectangle(screen, (x, y), (x+w, y+h), (0, 0, 255), 2)
        cv2.putText(screen, f"Conf: {res.confidence:.2f}", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite(str(out_path), screen)
    else:
        print("完全找不到！")

if __name__ == "__main__":
    main()
