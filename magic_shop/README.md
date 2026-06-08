# 魔法商店工作區

這個目錄給 AGY 獨立開發「魔法商店」任務使用。

## 邊界

AGY 只能修改 `magic_shop/` 內的檔案。可以讀取、import 或呼叫主專案工具，但不能修改 `src/`、`assets/`、`tests/`、`docs/` 或其他目錄。

## 建議工作流程

1. 先讀本目錄的 `AGENTS.md`、`CODEX_NOTES.md`、`QA.md`。
2. 讀主專案 `CODEX_NOTES.md` 中的安全規則。
3. 用既有截圖 `manual_screenshots/魔法商店/001_要購買.png` 先做離線分析。
4. 需要資產時，放在 `magic_shop/assets/`。
5. 需要腳本時，放在 `magic_shop/scripts/`。
6. 實機測試時，把截圖留在 `magic_shop/runtime_captures/` 或 `magic_shop/debug_output/`。

## 可用指令

```powershell
.\.venv-codex\Scripts\python.exe -m src.main check-device
.\.venv-codex\Scripts\python.exe -m src.main screenshot --name magic_shop_probe.png
.\.venv-codex\Scripts\python.exe -m src.main detect-scene
```

AGY 自己的腳本建議放在：

```powershell
.\.venv-codex\Scripts\python.exe magic_shop\scripts\<script_name>.py
```

## 停止條件

遇到下列情況要停下來問使用者：

- 不確定是否該買。
- 商品價格、數量、折扣、資源類型辨識不清楚。
- 找不到預期按鈕或畫面。
- 需要修改 `magic_shop/` 以外的程式碼。
- 需要新增需求判斷。

