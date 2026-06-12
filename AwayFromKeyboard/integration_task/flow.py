import time
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# 將專案根目錄加入 sys.path 以便匯入 src 模組
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.config import DEFAULT_SERIAL

class IntegrationFlow:
    def __init__(self):
        # 初始化裝置控制器與視覺匹配器
        self.device = DeviceController(serial=DEFAULT_SERIAL)
        self.matcher = VisionMatcher()
        self.templates_dir = Path(__file__).parent / "templates"
        
        if not self.device.connect():
            print("❌ [錯誤] 無法連線至 ADB 裝置")
            sys.exit(1)
            
        print("✅ 成功連線至 ADB 裝置")
        
        # 綁定特徵圖路徑
        self.tpl_000 = self.templates_dir / "000_掛機寶箱任務_target_1.png"
        self.tpl_000_close = self.templates_dir / "000_關閉寶箱_target_0.png"
        self.tpl_001 = self.templates_dir / "001_任務返回_target_3.png"
        self.tpl_002 = self.templates_dir / "002_進入王國事件_target_0.png"
        self.tpl_003 = self.templates_dir / "003_進入異界奇聞_target_0.png"
        self.tpl_003_2 = self.templates_dir / "002_進入異界奇聞2_target_8.png"
        self.tpl_005 = self.templates_dir / "005_返回_target_13.png"
        
        # 定義各自的 ROI (x, y, w, h) 以提升辨識穩定度
        self.roi_000 = (366, 306, 237, 183)
        self.roi_000_close = (529, 357, 264, 132)
        self.roi_001 = (0, 0, 146, 133)
        self.roi_002 = (0, 132, 152, 140)
        # 003 的 Y 軸跨度設為全畫面(或較大範圍) 540
        self.roi_003 = (0, 0, 278, 540)
        self.roi_005 = (0, 0, 141, 133)
        
        self.python_exe = str(PROJECT_ROOT / ".venv-codex" / "Scripts" / "python.exe")

    def find_and_tap(self, template_path, roi, step_name, desc, threshold=0.7, wait_after=2.0, max_attempts=5, swipe_left_menu=False):
        """
        在畫面中尋找目標特徵圖並點擊
        """
        for attempt in range(max_attempts):
            screen = self.device.screenshot()
            if screen is None:
                time.sleep(1)
                continue
                
            # 用非常低的門檻來獲取最佳匹配，藉此印出最大信心度供除錯
            res = self.matcher.match_template(screen, template_path, threshold=-1.0, roi=roi)
            max_conf = res.confidence if res else 0.0
            
            if res and res.confidence >= threshold:
                print(f"[{step_name}] 尋找 {desc}... 找到特徵圖 (信心度: {max_conf:.3f})，點擊成功。位置：{res.center}")
                self.device.tap(*res.center)
                time.sleep(wait_after)
                return True
                
            if swipe_left_menu:
                print(f"[{step_name}] 未找到 {desc} (目前最大信心度: {max_conf:.3f})，進行左側選單滑動尋找 ({attempt+1}/{max_attempts})...")
                # 實作左側選單的滑動：從下方滑到上方 (捲動畫面往下)
                self.device.swipe(150, 450, 150, 150, duration_ms=500)
                time.sleep(1.5)
            else:
                print(f"[{step_name}] 未找到 {desc} (目前最大信心度: {max_conf:.3f})，等待重試 ({attempt+1}/{max_attempts})...")
                time.sleep(1)
                
        print(f"[{step_name}] 尋找 {desc} 失敗！已達到最大嘗試次數。")
        return False

    def run(self):
        print("\n🚀 開始執行 Integration Flow...\n")
        
        # ----------------------------------------------------------------
        # Step 000：進入每日任務
        # ----------------------------------------------------------------
        if self.find_and_tap(self.tpl_000, self.roi_000, "Step 000", "寶箱", threshold=0.4, wait_after=2.0):
            # Step 000_1: 點擊彈窗的確定按鈕
            if self.find_and_tap(self.tpl_000_close, self.roi_000_close, "Step 000_1", "關閉寶箱確定按鈕", threshold=0.7, wait_after=3.0):
                print("[Step 000] 轉場完畢，準備執行 src.main run-all...")
                subprocess.run([self.python_exe, "-m", "src.main", "--debug", "run-all"], cwd=str(PROJECT_ROOT))
                print("[Step 000] daily tasks run-all 外部指令執行結束。")
            else:
                print("流程終止於 Step 000_1 (找不到確定按鈕)")
                return
        else:
            print("流程終止於 Step 000")
            return
            
        # ----------------------------------------------------------------
        # Step 001：從任務返回主畫面
        # ----------------------------------------------------------------
        if not self.find_and_tap(self.tpl_001, self.roi_001, "Step 001", "任務返回按鈕", threshold=0.7, wait_after=3.0):
            print("流程終止於 Step 001")
            return
            
        # ----------------------------------------------------------------
        # Step 002：進入王國事件
        # ----------------------------------------------------------------
        if not self.find_and_tap(self.tpl_002, self.roi_002, "Step 002", "王國事件入口", threshold=0.7, wait_after=3.0):
            print("流程終止於 Step 002")
            return
            
        # ----------------------------------------------------------------
        # Step 003：進入世界奇聞
        # ----------------------------------------------------------------
        print("\n[Step 003] 尋找 異界奇聞...")
        found_003 = False
        for attempt in range(8):
            screen = self.device.screenshot()
            if screen is None:
                time.sleep(1)
                continue
                
            res1 = self.matcher.match_template(screen, self.tpl_003, threshold=-1.0, roi=self.roi_003)
            res2 = self.matcher.match_template(screen, self.tpl_003_2, threshold=-1.0, roi=self.roi_003)
            
            c1 = res1.confidence if res1 else 0.0
            c2 = res2.confidence if res2 else 0.0
            
            if res1 and c1 >= 0.7:
                print(f"[Step 003] 找到未發亮特徵圖 (信心度: {c1:.3f})，點擊成功。位置：{res1.center}")
                self.device.tap(*res1.center)
                found_003 = True
                time.sleep(4.0)
                break
            elif res2 and c2 >= 0.55:
                print(f"[Step 003] 找到發亮特徵圖 (信心度: {c2:.3f})，點擊成功。位置：{res2.center}")
                self.device.tap(*res2.center)
                found_003 = True
                time.sleep(4.0)
                break
                
            max_c = max(c1, c2)
            print(f"[Step 003] 未找到 異界奇聞 (目前最大信心度: {max_c:.3f})，進行左側選單滑動尋找 ({attempt+1}/8)...")
            self.device.swipe(150, 450, 150, 150, duration_ms=500)
            time.sleep(1.5)
            
        if found_003:
            print("[Step 003] 轉場完畢，準備執行 ads2/cli.py run...")
            subprocess.run([self.python_exe, "ads2\\cli.py", "run", "--debug"], cwd=str(PROJECT_ROOT))
            print("[Step 003] ads2/cli.py 外部指令執行結束。")
        else:
            print("流程終止於 Step 003")
            return
            
        # ----------------------------------------------------------------
        # Step 004：從世界奇聞返回主畫面 (使用 005 的特徵圖)
        # ----------------------------------------------------------------
        if self.find_and_tap(self.tpl_005, self.roi_005, "Step 004", "主畫面返回按鈕", threshold=0.7, wait_after=3.0, max_attempts=5):
            print("\n🎉 Integration Flow 全部完成，已確保回到主畫面！")
        else:
            print("流程終止於 Step 004")

if __name__ == "__main__":
    flow = IntegrationFlow()
    flow.run()
