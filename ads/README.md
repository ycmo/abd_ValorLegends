# Ad Closer 廣告處理模組

本模組獨立負責處理 Valor Legends 中的「廣告觀看與關閉」流程，由 agy 維護。
與主線每日任務（src/）分離，提供乾淨獨立的介面供後續整合。

## 目錄結構

```text
ads/
├── cli.py               # 廣告工具命令列入口
├── assets/
│   ├── entry/           # 「觀看廣告」入口按鈕的 template
│   ├── ad_close/        # 存放各種廣告的 X / Close / Skip 按鈕 template (960x540解析度下)
│   └── anchors/         # 存放確認廣告關閉後的特徵 (例如遊戲大廳)
├── captures/            # 自行擷取的原始截圖存放區 (供手動裁切用)
├── debug/               # 執行失敗時的除錯截圖與匹配結果
└── README.md            # 說明文件
```

## 執行方式

進入 `ads` 目錄或在專案根目錄執行：

1. **一般測試**
   ```powershell
   python ads/cli.py --serial 127.0.0.1:5555
   ```

2. **偵錯模式 (輸出比對框線截圖)**
   ```powershell
   python ads/cli.py --debug
   ```

3. **自行擷取截圖 (供裁切)**
   ```powershell
   python ads/cli.py capture --tag my_ad_screenshot
   ```

## 設計理念與狀態機

- **只做廣告**：不碰觸主線的任何每日任務流程。
- **安全的狀態機**：
  1. `FIND_ENTRY`: 偵測畫面中是否有「觀看廣告」的入口按鈕。
  2. `TAP_ENTRY`: 點擊廣告入口，開始播放。
  3. `INITIAL_WAIT`: 等待廣告播放 (不掃描，避免浪費資源與誤判，預設等待約 25-30 秒)。
  4. `FIND_CLOSE`: 每秒擷圖一次，掃描畫面的四個角落。
  5. `TAP_CLOSE`: 找到 template 進行點擊。
  6. `VERIFY_RETURN`: 確認是否成功跳出廣告回到遊戲。
  7. `DONE` / `FAILED`: 不隨意發送 Back 鍵，失敗時僅紀錄並退出，保留現場供排查。
