# Valor Legends ADB 自動化工具

外部 Python 腳本，透過 ADB 控制 Android 模擬器，使用 OpenCV template matching 自動化遊戲操作。

**技術路線**：ADB 截圖 → OpenCV 比對 → ADB tap。無封包攔截、無記憶體修改、無 APK 注入。

---

## 環境需求

- Python 3.9+
- ADB（Android Debug Bridge）已安裝並加入 PATH
- Android 模擬器（已開啟 USB 偵錯 / ADB over TCP）

### 安裝 Python 套件

```bash
pip install -r requirements.txt
```

---

## 專案結構

```
adb_vl/
├── assets/
│   ├── ad_close/              ← 廣告關閉按鈕 template（*.png）
│   │   ├── close_x_01.png
│   │   ├── close_x_02.png
│   │   └── skip_01.png
│   └── anchors/               ← 遊戲大廳 anchor template
│       └── game_lobby_anchor.png
├── screenshots/
│   └── debug/                 ← debug 模式輸出截圖
├── src/
│   ├── adb_controller.py      ← DeviceController（連線、擷圖、tap、back）
│   ├── vision_matcher.py      ← VisionMatcher（ROI、多 template、debug 框）
│   ├── ad_closer.py           ← 廣告關閉狀態機 MVP
│   ├── actions.py             ← 舊有 CLI actions（probe-daily-tasks 等）
│   ├── adb_client.py          ← 舊有 ADB 底層
│   ├── vision.py              ← 舊有 vision 底層
│   └── main.py                ← CLI 入口
├── docs/
│   ├── daily_tasks_exploration.md
│   └── repo_inspection_report.md
├── requirements.txt
└── README.md
```

---

## 廣告關閉 MVP (`close-ad`)

### 快速開始

1. **手動開啟廣告**：在遊戲中點擊任一「觀看廣告」按鈕，讓廣告開始播放。
2. **準備 template**：先擷取一張截圖，裁切出廣告的 X / Close / Skip 按鈕，放入 `assets/ad_close/`：
   ```bash
   python src/main.py screenshot
   ```
3. **執行 MVP**（保持廣告播放中）：
   ```bash
   python src/main.py close-ad --debug
   ```

### 完整 CLI 參數

```
python src/main.py close-ad [OPTIONS]

選項：
  --serial        ADB 設備 serial（預設: 127.0.0.1:5555）
  --timeout       最長等待秒數（預設: 60）
  --interval      輪詢截圖間隔秒數（預設: 1.5）
  --threshold     Template matching 信心值閾值（預設: 0.82）
  --anchor-threshold  Anchor 偵測信心值（預設: 0.80）
  --ad-close-dir  Close button template 資料夾（預設: assets/ad_close）
  --anchor-path   遊戲大廳 anchor 圖片（預設: assets/anchors/game_lobby_anchor.png）
  --grace         廣告黑屏載入寬限期（秒，預設: 5）
  --post-tap-wait 點擊後等待秒數（預設: 2.5）
  --max-taps      最大點擊嘗試次數（預設: 5）
  --debug         輸出帶 bbox 的 debug 截圖到 screenshots/debug/
  --debug-dir     Debug 截圖輸出目錄（預設: screenshots/debug）
```

### 狀態機流程

```
[手動開廣告] → AD_WAIT
                 │ 每 1.5s 截圖，掃描四角 ROI
                 │ 找到 close/skip template
                 ↓
           FIND_CLOSE_OR_SKIP
                 │ 確認比對結果
                 ↓
              TAP_CLOSE
                 │ adb tap center
                 │ 等待 2.5s
                 │ 確認是否回到遊戲（anchor 或 close button 消失）
                 ├──→ DONE   ✅ 廣告關閉成功
                 └──→ FAILED ❌ timeout / 多次嘗試失敗 → 輸出 debug 截圖
```

### ROI 掃描範圍（預設）

| 區域         | 比例範圍（y%, x%）    | 說明                      |
| :----------- | :-------------------- | :------------------------ |
| top_right    | (0~20%, 70~100%)      | 最常見廣告 X 按鈕位置     |
| top_left     | (0~20%, 0~30%)        | 部分廣告的關閉在左上角    |
| bottom_right | (80~100%, 70~100%)    | Skip Ad 常見位置          |
| bottom_left  | (80~100%, 0~30%)      | 部分廣告格式              |

---

## 其他指令

```bash
# 列出設備
python src/main.py devices

# 擷圖
python src/main.py screenshot

# 點擊座標
python src/main.py tap 800 450

# 在截圖中尋找 template
python src/main.py find assets/ad_close/close_x_01.png

# 探測每日任務「前往」按鈕
python src/main.py probe-daily-tasks
```

---

## 注意事項

- 本工具為純外部 UI 自動化（ADB 截圖 + OpenCV 比對 + ADB tap），不涉及任何封包攔截、記憶體修改、APK 注入或反作弊規避。
- Template 圖片必須在與模擬器相同的解析度下擷取。
- FAILED 時腳本**不會**自動重啟遊戲或發送 back 鍵，僅輸出 debug 截圖供手動排查。
