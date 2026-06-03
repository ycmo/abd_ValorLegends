# Valor Legends 模擬器自動化 Bot 參考專案調研與分析報告

本報告針對第二階段 Candidate Repositories 進行深度檢驗，分析其技術架構、License、最近更新時間、風險性，並整理可借用的設計模式，最後為我們的 Valor Legends Python + ADB + OpenCV 專案提供最小實作建議與檔案結構設計。

---

## A. 候選專案可信度與技術可行性檢驗

| 專案名稱 / 網址 | 是否存在 | License 授權 | 最近更新時間 | Python + ADB + OpenCV 技術線符合度 | 高風險內容 | 評語與狀態分析 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. mibho/autoclient** | 是 | 無明確 License<br>（**不可直接複製**） | 2023 年 6 月<br>(約 3 年前) | **部分符合**<br>（擷圖用 Windows GDI，控制用 ADB sendevent） | 無 | 專案已被原作者標記為「scuffed & basically abandoned」。核心模組 `BotTools.py` 與 `BotFunctionsTools.py` 程式碼在 GitHub 上被**截斷 (truncated)**。擷圖採用 Windows API 直接抓取模擬器視窗而非 ADB 擷圖。 |
| **2. illuap/mobile-bot** | 是 | 無明確 License<br>（**不可直接複製**） | 2019 年 3 月<br>(約 7 年前) | **不符合**<br>（使用 PyAutoGUI 模擬 PC 桌面的滑鼠點擊） | 無 | 專案為《King's Raid》自動化，採用 PyAutoGUI 抓圖及點擊，底層不使用 ADB。目前已處於封存狀態，不具備 ADB 參考價值。 |
| **3. AntonKukoba1/IdleBotDH** | 是 | 無明確 License<br>（**不可直接複製**） | 2022 年 3 月<br>(約 4 年前) | **不符合**<br>（使用 Lackey 進行主機端畫面控制） | 無 | 專案為《Idle Heroes》自動化，採用 `lackey` 影像識別庫（底層為 OpenCV 的 Java-Sikuli 封裝）。完全不使用 ADB，而是直接模擬 Windows 桌面滑鼠，高度依賴模擬器最大化（1920x1080）與滑鼠焦點。 |
| **4. DragonChen-TW/bot_prac** | 是 | 無明確 License<br>（**不可直接複製**） | 2018 年 8 月<br>(約 8 年前) | **部分符合**<br>（使用 ADB + OpenCV 樣板比對） | 無 | 只有 2 次 commit 的練習專案。使用 subprocess 呼叫 `tool/adb.exe` 發送 tap/swipe，並讀取 template 比對。檔案在 GitHub 上同樣被截斷。 |
| **5. 額外補充 1 (推薦)<br>Meowcolm024/FGO-Automata** | 是 | **BSD-3-Clause**<br>（**可參考與複製**） | 2022 - 2023 年 | **完全符合**<br>（Python + ADB 記憶體擷圖 + OpenCV） | 無 | 程式碼架構完整，檔案未截斷，有完整的設備控制 (ADB) 與影像識別分離設計，是實作 Python + ADB 自動化的極佳參考。 |
| **6. 額外補充 2 (推薦)<br>LearnCodeByGaming/opencv_tutorials** | 是 | **Unlicense / MIT**<br>（**可完全複製**） | 穩定教學專案 | **影像模組符合**<br>（最標準的 Python OpenCV 比對實作） | 無 | 提供最完整、高效的 OpenCV Template Matching 教學程式碼。其多目標比對、信心值篩選與 Debug 畫框的封裝方式是業內標準。 |

---

## B. 可借用設計與架構整理

根據上述專案的調研，我們整理出以下在設計「Python + ADB + OpenCV」自動化 Bot 時的關鍵設計與優化策略（不照抄程式碼，只借用其設計思想）：

### 1. ADB 擷圖 (screencap) 與記憶體轉換
* **傳統慢速作法**：`adb shell screencap -p /sdcard/s.png` ➡️ `adb pull` ➡️ `cv.imread()`。這會產生兩次磁碟寫入與傳輸，每次擷圖耗時 1 - 2 秒，極度影響效能。
* **推薦優化設計**（參考 `Meowcolm024/FGO-Automata`）：
  * 直接利用 Python `subprocess.Popen` 執行 `adb shell screencap -p`。
  * 通過管道（stdout）直接讀取二進位資料流。
  * **Windows 平台避坑**：Windows 的 ADB 在傳輸二進位流時會將 `\n` 自動轉換為 `\r\n`，導致 PNG 標頭毀損。必須在程式中將 `\r\r\n` 或 `\r\n` 進行二進位替換（Replace），然後使用 `cv2.imdecode()` 直接在記憶體中將 bytearray 解碼為 OpenCV 的 BGR 矩陣。
  ```python
  # 設計概念：透過 Popen 取得標準輸出二進位流
  # 移除 Windows ADB 傳輸造成的換行字元干擾後解碼
  image = cv.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv.IMREAD_COLOR)
  ```

### 2. 影像比對 (Template Matching) 與區域過濾 (ROI)
* **區域比對 (ROI - Region of Interest)**（參考 `mibho/autoclient`）：
  * 不要對全螢幕 (例如 1920x1080) 進行 `matchTemplate`。這不僅運算慢，還極易因為背景有相似顏色而造成誤判。
  * 先對當前截圖進行切片（例如 `cropped = screen[y1:y2, x1:x2]`），只在可能出現該按鈕的範圍內進行比對。
* **信心值與中心點定位**（參考 `LearnCodeByGaming`）：
  * 使用 `cv.matchTemplate(img, template, cv.TM_CCOEFF_NORMED)`。
  * 使用 `cv.minMaxLoc()` 取得 `max_val`（匹配相似度，0.0 ~ 1.0）與 `max_loc`（匹配到的左上角座標）。
  * 設定閾值（例如 `threshold = 0.85`）。若 `max_val >= threshold`，則計算中心點點擊座標：
    $$\text{center\_x} = \text{max\_loc\_x} + \frac{\text{template\_width}}{2}$$
    $$\text{center\_y} = \text{max\_loc\_y} + \frac{\text{template\_height}}{2}$$

### 3. Tap / Swipe / Back 封裝
* **設備定位**：在 Device 類別中儲存設備 serial（例如 `127.0.0.1:5555`），所有 ADB 指令皆加上 `-s {serial}`，以支援多開模擬器。
* **延遲防抖設計**：由於模擬器與遊戲載入需要時間，每次 `tap` 或 `swipe` 動作後，封裝函數內應自動帶有隨機的微小等待時間（例如 `time.sleep(0.5 + random.uniform(0.1, 0.3))`），這降低點擊過快導致遊戲無響應的問題。

### 4. 狀態機與主循環 (State Machine & BotLoop)
* **檢測導向狀態機**：`BotLoop` 每輪擷圖後，會依據「目前狀態」優先比對特定樣板。
* **彈窗阻擋與未知狀態恢復 (Recovery)**：
  * 在自動化過程中，常會出現「公會引導彈窗」、「廣告彈窗」或「斷線重連」。
  * **設計策略**：
    1. 設置一個 retry 計數器或逾時時間。
    2. 若持續 10 秒比對不到任何目標樣板，則執行「未知狀態恢復機制」。
    3. 恢復機制第一步：發送 Back 鍵 `keyevent 4` 以嘗試關閉彈窗；或者點擊畫面空白處。
    4. 恢復機制第二步：點擊固定在大廳底部的「掛機」分頁座標 `(800, 840)`，強行拉回遊戲大廳，再重新打開任務頁面。

### 5. 除錯輸出 (Debug System)
* **畫框除錯**（參考 `LearnCodeByGaming`）：
  * 當開啟 `debug = True` 時，在主截圖上使用 `cv.rectangle()` 劃出紅框框選匹配到的位置，並用 `cv.putText()` 將信心值寫在旁邊。
  * 將此畫框後的截圖儲存至 `screenshots/debug_match.png`，便於開發者調整閾值。

---

## C. 專案最小實作建議 (Minimum Viable Implementation)

為保證我們 Valor Legends 專案的簡潔與高維護性，建議目前**不要**導入複雜的狀態機庫，而是手寫一個最輕量且健壯的架構：

```
adb_vl/
├── assets/                    # 存放按鈕與 UI 樣板小圖 (.png)
│   ├── go_btn.png             # 「前往」按鈕樣板
│   ├── close_btn.png          # 「關閉/否」按鈕樣板
│   └── main_lobby_flag.png    # 主大廳特徵（如掛機分頁的某個獨特 icon）
├── docs/                      # 專案文檔
│   └── daily_tasks_exploration.md
├── src/
│   ├── __init__.py
│   ├── adb_controller.py      # DeviceController: 連線、二進位擷圖、tap、back 封裝
│   ├── vision_matcher.py      # VisionMatcher: matchTemplate, ROI 裁剪, 信心座標計算
│   ├── bot_loop.py            # BotLoop: 核心任務狀態判斷與控制循環
│   └── main.py                # 程式啟動點
├── requirements.txt           # 僅包含 opencv-python, numpy
└── README.md
```

### 1. DeviceController 核心設計
```python
# src/adb_controller.py 設計概念
import subprocess
import numpy as np
import cv2 as cv

class DeviceController:
    def __init__(self, device_address="127.0.0.1:5555"):
        self.device = device_address
        self.adb_path = "adb" # 確保系統環境變數有 adb，或指向本機路徑
        self.connect()

    def connect(self):
        subprocess.run([self.adb_path, "connect", self.device], stdout=subprocess.DEVNULL)

    def send_tap(self, x, y):
        subprocess.run([self.adb_path, "-s", self.device, "shell", "input", "tap", str(x), str(y)])

    def send_back(self):
        subprocess.run([self.adb_path, "-s", self.device, "shell", "input", "keyevent", "4"])

    def get_screenshot(self):
        # 採用管道讀取二進位流以提升效能
        cmd = [self.adb_path, "-s", self.device, "shell", "screencap", "-p"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        raw_bytes = process.communicate()[0]
        
        # Windows 平台下將 \r\r\n 替換為 \n 的資料校正 (二進位處理)
        # 此處需依據 Windows 實際傳回位元組進行 replace 處理
        # 避免圖片毀損，隨後進行解碼
        img_array = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv.imdecode(img_array, cv.IMREAD_COLOR)
```

### 2. VisionMatcher 核心設計
```python
# src/vision_matcher.py 設計概念
import cv2 as cv

class VisionMatcher:
    def __init__(self):
        pass

    def match(self, screen_img, template_path, threshold=0.85, roi=None):
        """
        在 screen_img 中尋找 template。
        roi 格式為: [y_start, y_end, x_start, x_end]
        """
        template = cv.imread(template_path, cv.IMREAD_COLOR)
        h, w = template.shape[:2]

        search_img = screen_img
        offset_x, offset_y = 0, 0

        # 若有指定 ROI 範圍，則先進行裁剪以優化效能與準確度
        if roi:
            y1, y2, x1, x2 = roi
            search_img = screen_img[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1

        result = cv.matchTemplate(search_img, template, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)

        if max_val >= threshold:
            # 計算在原始大圖上的中心點座標
            center_x = max_loc[0] + offset_x + (w // 2)
            center_y = max_loc[1] + offset_y + (h // 2)
            return {"success": True, "confidence": max_val, "center": (center_x, center_y), "bbox": (max_loc[0] + offset_x, max_loc[1] + offset_y, w, h)}
        
        return {"success": False, "confidence": max_val, "center": None, "bbox": None}
```

### 3. BotLoop 核心設計
```python
# src/bot_loop.py 設計概念
import time
import os

class BotLoop:
    def __init__(self, controller, matcher):
        self.device = controller
        self.matcher = matcher
        self.running = True

    def run(self):
        print("Valor Legends 最小自動化任務循環已啟動...")
        while self.running:
            # 1. 擷取最新畫面
            screen = self.device.get_screenshot()
            
            # 2. 優先檢測是否有阻擋的「關閉/否」按鈕
            close_result = self.matcher.match(screen, "assets/close_btn.png", threshold=0.85)
            if close_result["success"]:
                cx, cy = close_result["center"]
                print(f"[DEBUG] 偵測到關閉彈窗，進行點擊: ({cx}, {cy})")
                self.device.send_tap(cx, cy)
                time.sleep(2)
                continue

            # 3. 比對「前往」按鈕 (設定 ROI 在右側按鈕區 y: 150-880, x: 1200-1500)
            go_result = self.matcher.match(screen, "assets/go_btn.png", threshold=0.85, roi=[150, 880, 1200, 1500])
            if go_result["success"]:
                cx, cy = go_result["center"]
                print(f"[LOG] 找到「前往」按鈕 (Confidence: {go_result['confidence']:.2f}) ➡️ 點擊座標: ({cx}, {cy})")
                self.device.send_tap(cx, cy)
                
                # 進入等待，給予遊戲 4.5 秒跳轉並加載 3D 資源的時間
                time.sleep(4.5)
                
                # 此處可加入進入頁面後的子任務處理，或直接觸發返回序列
                self.recover_to_lobby()
                continue
            
            print("[DEBUG] 未檢測到可操作目標，等待下一輪...")
            time.sleep(2)

    def recover_to_lobby(self):
        """依據前階段探索之返回序列，強制退回每日任務頁"""
        print("[LOG] 啟動導航返回序列...")
        self.device.send_back()
        time.sleep(1.5)
        # 點擊「否」關閉退出提示
        self.device.send_tap(385, 745)
        time.sleep(1.0)
        # 點擊底部「掛機」分頁
        self.device.send_tap(800, 840)
        time.sleep(2.0)
        # 點擊右上「任務」入口
        self.device.send_tap(1555, 100)
        time.sleep(3.0)
```

---

## D. 綜合調研結論與推薦

### 1. 最推薦參考的 1 個 repo：`Meowcolm024/FGO-Automata` (補充)
* **原因**：它是目前網路上最標準、且程式碼**完整未截斷**的「Python + ADB + OpenCV」手動控制架構。其 Device 控制層與 Image Processing 層完全解耦，並使用標準 BSD 授權，最適合我們直接作為專案的底層設計框架。
* *(若只限原候選清單，則最推薦 `mibho/autoclient`。其 ROI 比對策略與 Coords 管理模式極佳，但截圖用 GDI 且代碼截斷，需要手動補齊。)*

### 2. 次推薦的 1 個 repo：`DragonChen-TW/bot_prac` (原候選 4)
* **原因**：在原候選清單中，它是唯一真正實作了 Python 呼叫 `adb.exe` 指令進行模擬器點擊與擷圖的專案。雖然極為簡陋且代碼截斷，但能作為我們寫 subprocess 包裝時的快速對照。

### 3. 目前應該直接忽略的 repo：`illuap/mobile-bot` 與 `AntonKukoba1/IdleBotDH`
* **原因**：兩者都**不使用 ADB 通訊**，而是使用 PyAutoGUI 或 Lackey 對 Windows 實體桌面進行滑鼠控制。這會導致我們的腳本與 Windows 桌面環境綁定（畫面不能被遮擋、視窗解析度必須固定、滑鼠焦點會被強行奪走），完全不符合我們「外部模擬器 ADB 自動化（可後台運行）」的技術路線，應直接忽略其輸入控制邏輯。
