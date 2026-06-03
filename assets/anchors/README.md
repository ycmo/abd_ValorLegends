# 遊戲大廳 Anchor Template 資料夾

此目錄存放「遊戲已回到大廳」的特徵圖片（Anchor Template）。

## 用途

廣告關閉後，腳本會用此 anchor 圖片確認畫面已回到遊戲主畫面（非廣告）。
若找到 anchor（信心值 >= anchor_threshold），則判定廣告成功關閉（DONE）。

## 如何擷取 Anchor

1. 回到 Valor Legends 遊戲主畫面（掛機分頁或大廳）
2. 執行 `python src/main.py screenshot`
3. 裁切一個「在廣告中絕對不會出現的遊戲 UI 特徵」，例如：
   - 底部導覽列的「掛機」圖示
   - 右上角的角色暱稱或鑽石圖示
   - 任何遊戲 HUD 固定元素

4. 儲存為 `game_lobby_anchor.png` 放入此目錄。

## 注意事項

- 若此目錄為空或圖片不存在，腳本改用「close button 消失」判定廣告關閉，
  雖然較不精確但仍可運作。
- Anchor 解析度必須與模擬器截圖一致。
- 不要選擇動態元素（例如動畫、數字倒計時）作為 anchor。
