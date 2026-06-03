# Game Lobby Anchor（選填）

遊戲大廳特徵圖，用來確認廣告已關閉並回到遊戲畫面。

## 如何製作
1. 回到 Valor Legends 遊戲主畫面（掛機分頁）
2. 執行 `python src/main.py screenshot`
3. 裁切一個**廣告中絕不會出現的固定 UI 元素**，例如：
   - 底部導覽欄圖示
   - 右上角的角色名稱或鑽石圖示
4. 存為 `game_lobby_anchor.png` 放入此目錄

## 若不提供此圖片
腳本改用「close button 消失」判定廣告是否關閉，仍可正常運作。
