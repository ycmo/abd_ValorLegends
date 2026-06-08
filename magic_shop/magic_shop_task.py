from __future__ import annotations

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import TaskSpec
from src.task_runner import BaseTask
from src.exceptions import TaskFailedError
from src.ocr_utils import build_easyocr_reader, read_texts_easyocr, parse_power_value

class MagicShopTask(BaseTask):
    # Dummy spec since we run it independently for now
    spec = TaskSpec(
        key="magic_shop",
        display_name="Magic Shop",
        asset_dir=Path(__file__).parent / "assets",
        daily_label_asset="None",
    )
    
    # 你裁切出來的想買的商品與按鈕
    TARGET_ITEMS = [
        "紫珠800.png",
        "紫珠960k.png",
        "競技場券480k.png",
        "競技場券5.png",
        "英雄碎片1800k.png",
        "英雄碎片30.png",
        "金牌10.png",
        "金牌5000k.png"
    ]
    
    def __init__(self, context):
        super().__init__(context)
        self._ocr_reader = None
        
    def _get_ocr_reader(self):
        if self._ocr_reader is None:
            self._ocr_reader = build_easyocr_reader()
        return self._ocr_reader

    def get_current_coins(self, screen) -> int:
        # 假設金幣在畫面右上角，取 y=0~80, x=400~960
        roi = (400, 0, 560, 80)
        fragments = read_texts_easyocr(screen, roi=roi, reader=self._get_ocr_reader())
        
        print(f"  [OCR] 偵測到的文字片段: {fragments}")
        
        max_val = -1
        for frag in fragments:
            text = str(frag['text']).lower().replace(',', '').replace(' ', '')
            
            # 如果有 M，例如 12.3m 或 12m
            if 'm' in text:
                import re
                match = re.search(r"(\d+(?:\.\d+)?)m", text)
                if match:
                    val = float(match.group(1)) * 1000  # 轉成 k
                    max_val = max(max_val, int(val))
                    continue
            
            # 處理 k 或一般數字
            val = parse_power_value(text)
            if val > max_val:
                max_val = val
                
        return max_val

    def buy_items_on_screen(self) -> int:
        bought_count = 0
        while True:
            screen = self.context.controller.screenshot()
            found_any = False
            
            for item in self.TARGET_ITEMS:
                path = self.asset_path(item)
                if not path.exists():
                    continue
                    
                match = self.context.matcher.match_template(screen, path, threshold=0.82)
                if match is not None:
                    print(f"  ➡️ 找到目標商品：{item}，點擊中...")
                    self.context.controller.tap(*match.center)
                    time.sleep(1.0)
                    
                    # 點擊商品後，尋找購買按鈕
                    buy_btn_path = self.asset_path("購買.png")
                    if buy_btn_path.exists():
                        buy_screen = self.context.controller.screenshot()
                        buy_match = self.context.matcher.match_template(buy_screen, buy_btn_path, threshold=0.82)
                        if buy_match is not None:
                            self.context.controller.tap(*buy_match.center)
                            print(f"    ✅ 點擊了購買按鈕！")
                            time.sleep(1.5)
                            
                            # 點擊空白處關閉獲得道具提示 (隨意點擊左上角空白處)
                            self.context.controller.tap(80, 500)
                            time.sleep(1.0)
                            bought_count += 1
                            found_any = True
                            break # 買完一個後，跳出迴圈重新截圖，以確保畫面狀態最新
                    
            # 如果整圈跑完都沒有找到任何可買的商品，代表這一頁已經清空
            if not found_any:
                break
                
        return bought_count

    def execute(self) -> str:
        total_bought = 0
        max_refreshes = 15
        refreshes = 0
        
        while refreshes < max_refreshes:
            print(f"\n=========================================")
            print(f"商店第 {refreshes + 1} 頁掃描開始...")
            print(f"=========================================")
            
            # 1. 買畫面上現有的
            bought = self.buy_items_on_screen()
            total_bought += bought
            
            # 2. 往下滑 (座標可能需要依照模擬器調整)
            print("  向下捲動查看更多商品...")
            self.context.controller.swipe(480, 450, 480, 150, duration_ms=500)
            time.sleep(1.0)
            
            # 3. 買滑動後的
            bought = self.buy_items_on_screen()
            total_bought += bought
            
            # 4. 判斷是否刷新
            screen = self.context.controller.screenshot()
            
            # 檢查 100 紅鑽按鈕
            refresh_btn_path = self.asset_path("刷新100.png")
            if not refresh_btn_path.exists():
                print("❌ 找不到 刷新100.png 參考圖片，終止任務。")
                break
                
            refresh_match = self.context.matcher.match_template(screen, refresh_btn_path, threshold=0.82)
            if refresh_match is None:
                print("⚠️ 畫面上沒有「100紅鑽」刷新按鈕 (可能變更貴了)，停止刷新。")
                break
                
            # 檢查金幣
            coins = self.get_current_coins(screen)
            print(f"💰 目前偵測到的金幣數量：{coins}k")
            
            if coins < 12000:
                print(f"⚠️ 金幣小於 12000k，保留財力，停止刷新。")
                break
                
            # 點擊刷新
            print("🔄 條件滿足，點擊刷新！")
            self.context.controller.tap(*refresh_match.center)
            time.sleep(1.5)
            # 若刷新需要二次確認，我們可以在這裡寫死點擊 (目前假設直接點擊就能刷新)
            
            refreshes += 1

        print(f"\n🎉 魔法商店自動購買結束！")
        return f"Bought {total_bought} items, refreshed {refreshes} times."
