# 廣告關閉按鈕 Template 圖片資料夾

此目錄存放廣告關閉相關按鈕的 Template 圖片（PNG 格式）。

## 命名建議

| 檔名              | 說明                        |
| :---------------- | :-------------------------- |
| close_x_01.png    | 廣告右上角「X」關閉按鈕     |
| close_x_02.png    | 另一款廣告的「X」樣式       |
| skip_01.png       | 「Skip Ad」跳過廣告按鈕     |
| close_btn_01.png  | 「CLOSE」文字按鈕           |

## 如何擷取 Template

1. 先手動播放一個廣告，待廣告接近結尾時（Skip / Close 按鈕出現）：
   ```
   python src/main.py screenshot
   ```
   截圖存至 `screenshots/current.png`。

2. 用圖片編輯器（Paint / Photoshop / IrfanView）開啟截圖，
   裁切出 close/skip 按鈕的最小區塊，存為 PNG。

3. 圖片大小建議：約 40×40 ~ 100×80 像素（不要太大，也不要只有幾個像素）。

4. 放入此資料夾後，執行 `close-ad` 指令即可自動載入。

## 注意事項

- 解析度必須與模擬器截圖一致（例如全部在 1600×900 下擷取）。
- 避免包含背景色塊（只保留按鈕本身）。
- 可以同時放多張，腳本會自動選信心值最高的結果。
