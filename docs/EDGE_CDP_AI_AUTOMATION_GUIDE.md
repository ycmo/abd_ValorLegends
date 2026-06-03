# Edge CDP 多 AI 對話框自動化避坑指南

這份文件整理 AI Arena 開發與測試時，使用 agent 透過 Microsoft Edge CDP 連到多個 AI 網頁對話框的實務經驗。目標是給另一個在 Windows PowerShell 上執行的專案參考，避免重踩環境、登入、分頁、長 prompt、回應擷取、CAPTCHA、log 與 auditor 的坑。

## 一句話結論

如果專案直接在 Windows PowerShell 執行，會比 WSL/Codex sandbox 容易很多：agent 可以直接連 `http://127.0.0.1:9222`，通常不需要 WSL portproxy、C# bridge、`127.0.0.1:9223` tunnel、防火牆轉發。

但 PowerShell 只解決「連線通道」問題，不會自動解決以下問題：

- Edge 必須用 remote debugging port 和固定 profile 啟動。
- 各 AI 網站必須先在同一個 profile 登入。
- 已存在分頁要不要沿用，必須明確定義。
- 每個 AI 的輸入框、送出按鈕、停止按鈕、回應 DOM 都不同。
- 長 prompt 很容易造成輸入框填入不完整、送出失敗或回應超時。
- CAPTCHA / login gate 不能硬闖，必須標記 unavailable 或 pending。
- auditor 必須看完整 log，不能看截斷 log。

## 1. Edge 啟動方式

建議永遠使用獨立 profile，不要用平常瀏覽器 profile。

```powershell
$Edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $Edge)) {
  $Edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
}

& $Edge `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\Edge_CDP_Profile" `
  "https://chatgpt.com/"
```

啟動後立刻驗證：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version
```

看到 `Browser` 和 `webSocketDebuggerUrl` 才算 CDP 真的起來。

## 2. Edge 啟動等待不要寫死 3 秒

我們踩過一次：系統自動啟動 Edge 後只等 3 秒，結果 CDP 還沒 listening，程式誤判失敗。

正確做法是輪詢等待：

```powershell
$deadline = (Get-Date).AddSeconds(30)
do {
  try {
    $version = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version -TimeoutSec 2
    if ($version.StatusCode -eq 200) { break }
  } catch {
    Start-Sleep -Seconds 1
  }
} while ((Get-Date) -lt $deadline)
```

建議：

- 最多等 30 秒。
- 每秒檢查一次 `/json/version`。
- 不要只檢查 `msedge.exe` process 存在，process 存在不代表 CDP port 可用。

## 3. profile 與登入狀態

AI 網頁自動化的前提是同一個 `--user-data-dir` 裡已經登入。

建議流程：

1. 用 CDP profile 開 Edge。
2. 手動登入所有平台。
3. 不要再換 `--user-data-dir`。
4. agent 只接管這個 profile。

常見坑：

- 用一般 Edge 登入，但 agent 開的是 `C:\Edge_CDP_Profile`，結果仍是未登入。
- Windows 重新開機後 Edge process 消失，但 profile 還在，需要重開 CDP Edge。
- 使用同一 profile 開兩個普通 Edge / CDP Edge，可能造成新命令被舊 process 吃掉，remote debugging 沒真的生效。

如果要強制乾淨重啟：

```powershell
Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
& $Edge --remote-debugging-port=9222 --user-data-dir="C:\Edge_CDP_Profile"
```

## 4. PowerShell 專案通常不用 WSL portproxy

如果程式本體也在 Windows PowerShell 跑：

- CDP URL 用 `http://127.0.0.1:9222`。
- 不需要 `netsh interface portproxy`。
- 不需要 firewall rule。
- 不需要 WSL nameserver IP。
- 不需要 `127.0.0.1:9223` tunnel。

只有以下情況才需要 portproxy / firewall：

- agent 跑在 WSL，Edge 跑在 Windows。
- agent 跑在容器或 VM，連不到 Windows localhost。
- 需要從另一台機器連這個 CDP port。

注意：`--remote-debugging-address=0.0.0.0` 會擴大暴露面。若只是本機 PowerShell，通常不要用。

## 5. CDP 連線策略

建議自動化程式開頭先做三件事：

1. 檢查 `http://127.0.0.1:9222/json/version`。
2. 若不通，啟動 Edge。
3. 輪詢到 CDP 可用，再建立 Playwright / Selenium / CDP connection。

Playwright Python 範例概念：

```python
browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
context = browser.contexts[0] if browser.contexts else await browser.new_context()
```

重要：使用 `connect_over_cdp` 是「接管既有瀏覽器」，不是 Playwright 自己 launch browser。這也是能使用已登入 session 的原因。

## 6. 分頁策略：沿用還是新對話

這是核心產品決策，不能模糊。

我們最後採用的期望是：

- 如果目標網站分頁已開著，就沿用。
- 如果不存在，才開新分頁。
- 不要每次都強制開新網頁。

但沿用分頁有一個大坑：歷史對話會污染新任務。

建議分清楚兩層：

- **沿用分頁**：使用同一個已登入 tab，避免重新登入。
- **新對話**：在該 tab 內點「New chat」或導向新 conversation，避免上下文污染。

不同任務建議默認使用「同一 tab 的新對話」。如果使用者明確要接續前文，才沿用同一 conversation。

## 7. Archon / participant 分頁要隔離

如果同一平台同時扮演主持人和參賽者，不能共用同一 conversation。

例子：

- Perplexity 當 Archon。
- Perplexity 同時也可當 participant。

這兩者需要不同 tab 或至少不同 conversation。否則主持 prompt 和參賽 prompt 會混在同一串，後續回應會錯位。

做法：

- 分頁建立時標記用途，例如 `is_archon=true`。
- 找既有 tab 時不只看 URL，也看用途標記。
- 找不到同用途 tab 才開新 tab。

## 8. 對話框填入 prompt 的坑

不要用 `keyboard.type()` 處理長 prompt。它慢，而且換行可能被平台當成送出或造成斷裂。

優先順序建議：

1. `locator.fill(prompt)`。
2. 若 contenteditable 不支援 fill，用 JS 設定 `textContent` / `innerHTML` 並 dispatch `input` event。
3. 最後才用 `keyboard.insert_text(prompt)`。

不要使用會逐鍵模擬的 `type()`，尤其是：

- 長 prompt。
- 多行 prompt。
- 含 Markdown 表格。
- 含程式碼區塊。
- 含中文與標點混排。

## 9. 填入後一定要 readback

長 prompt 最大風險之一是「看似填入成功，其實只進去一半」。

送出前應該讀回輸入框內容，至少檢查：

- 長度是否接近。
- prompt 尾端 80 字是否存在。
- normalized whitespace 後是否相等。

如果 readback mismatch，直接報錯，不要送出。

例外：有些平台輸入框會把換行或空白正規化，所以不要只做 byte-for-byte 比對。

## 10. 送出按鈕不要只靠一個 selector

每個平台送出按鈕都不穩定，常見 selector 需要多路 fallback：

- `button[aria-label*="Send" i]`
- `button[aria-label*="Submit" i]`
- `button[aria-label*="送" i]`
- `button[aria-label*="发送" i]`
- `button[type="submit"]`

按鈕可見不代表可點，要檢查：

- visible
- enabled
- `disabled`
- `aria-disabled`
- 是否被 CAPTCHA overlay 擋住

如果 click 被 overlay 攔截，不要 retry 到死。這通常表示 login/CAPTCHA gate，要標記平台不可用。

## 11. 回應等待：不要只看文字有沒有變

AI 網站常見狀況：

- 回應一開始是空的。
- 先出現 loading / stop button。
- 文字流式更新。
- 最後 stop button 消失。
- DOM 可能產生多個 assistant message。

建議等待邏輯：

1. 送出前記錄 response count 和 latest response text。
2. 送出後等 generation start：
   - response count 增加，或
   - stop button 出現，或
   - latest response text 改變。
3. generation start 後持續抽取最新 assistant text。
4. text 連續穩定 N 秒，且 busy indicator 消失，才算完成。
5. 設 `empty_timeout` 和 `max_response_timeout`。

不要只等固定秒數。

## 12. timeout 與 PENDING 機制

有些平台會很慢，尤其是長 prompt 或搜尋型平台。

建議區分：

- `empty_timeout`：送出後多久內必須看到生成開始。
- `stable_duration`：文字穩定多久算完成。
- `max_response_timeout`：整體最多等多久。

若超時，不要讓整場卡死。回傳結構化狀態：

```json
{
  "status": "pending",
  "platform": "doubao",
  "round": 1,
  "reason": "generation did not start within empty_timeout",
  "snapshot": "logs/snapshots/doubao_....html"
}
```

不要只回傳裸字串 `[PENDING]`，除非只是過渡方案。結構化狀態才能讓主持流程正確判斷是否要略過、重試或要求使用者處理。

## 13. CAPTCHA / login gate 必須當成 hard stop

我們在 Doubao 踩到的問題：

- 系統偵測到 CAPTCHA / verification gate。
- 但程式仍嘗試送 prompt。
- 結果 click 被 `captcha_container` 攔截。
- retry / reload 後，有時會進新對話，有時又抓到污染內容。

經驗結論：如果偵測到 CAPTCHA 或明確 login gate，不要硬送 prompt。

正確行為：

- 立即標記該平台本輪 unavailable / pending。
- 存 screenshot + HTML。
- UI 提示使用者手動解 CAPTCHA / 重新登入。
- 主流程可以跳過該平台，不要讓整場失敗。

## 14. Doubao 特別注意

Doubao 目前是高風險平台，尤其在自動化測試中：

- CAPTCHA / verification gate 出現頻率較高。
- 有時 guest mode 看似能用，但穩定性差。
- reload 後可能回到新對話，也可能殘留歷史對話。
- 輸出可能受舊上下文或網站推薦內容污染。
- send button 可能被 CAPTCHA overlay 攔截。

建議：

- Doubao 開始前先做健康檢查。
- 發現 CAPTCHA 就不要送。
- 每次任務盡量新對話。
- response 要做基本合規檢查，例如是否包含明顯無關詞、是否只是 prompt echo、是否出現歷史任務關鍵字。
- 如果 Round 1 已 PENDING，後續是否允許再次點名 Doubao 要有策略，不要默默恢復。

## 15. Meta AI 特別注意

Meta AI 可用，但要注意：

- contenteditable input 需要 readback。
- 有時會先生成短 title-like message，不能太早判定完成。
- 回應格式常不如其他平台嚴格遵守 prompt。
- 如果要當 participant OK；如果要當 Archon，要確認 constructor / page role 隔離能處理。

等待 Meta 回應時，建議至少要求：

- 文字長度超過某個最小值，或
- busy indicator 消失後再穩定數秒。

## 16. Perplexity 特別注意

Perplexity 常適合當 Archon，因為它對調度與總結反應快。

坑：

- 登入/升級 modal 可能遮住輸入框。
- search input selector 可能是 textarea，也可能是 contenteditable。
- 同平台同時當 Archon 和 participant 時必須隔離 conversation。
- response selector 不能只抓第一個 `.prose`，應抓最新 assistant block。

## 17. ChatGPT 特別注意

ChatGPT 通常穩，但：

- textarea / ProseMirror DOM 會更新。
- 送出按鈕狀態變化快。
- 長 prompt 後需要等 UI 消化，不要 fill 完馬上點。
- 若使用 Enter 送出，確認不是只換行。

建議優先 click send button，不要依賴 Enter。

## 18. Gemini 特別注意

Gemini 的輸入框可能是 Quill editor / contenteditable。

建議：

- JS 清空時 dispatch `input` event。
- fill 失敗時用 `keyboard.insert_text`。
- 等送出按鈕 enabled。
- response 可能包含引用/額外 UI，需要 extractor 過濾。

## 19. DeepSeek 特別注意

DeepSeek 相對穩，但：

- 思考區塊可能混在 DOM 裡。
- 抽取 response 時不要把 internal thinking 或 prompt echo 當最終回答。
- 如果透過 clone/remove DOM 節點抽取，注意換行和表格可能遺失。

## 20. Claude / Auditor 特別注意

Claude 作 auditor 可以，但必須控制 prompt 大小和資料完整性。

我們踩到的 auditor 主要坑：

- Auditor 讀的是 `prompt_log.txt`。
- `prompt_log.txt` 裡 prompt/response 被截斷。
- 因此 auditor 以不完整資料判斷「抓錯內容」或「角色缺席」，容易誤判。

正確做法：

- 保留完整 raw log，例如 `prompt_log_full.txt`。
- 給 UI 顯示可用截斷 log，但 auditor 必須讀完整 log。
- 或者 auditor 讀 `session_dumps/*_conversation.md`。
- auditor prompt 必須包含本次實際配置：participants、archon、rounds、平台狀態。
- 不要讓 auditor 用 README 舊預設來判斷誰缺席。

## 21. log 設計

至少分三種 log：

1. **UI log**：給人看，可截斷。
2. **raw prompt/response log**：完整，不截斷，給 auditor 和 debug。
3. **event log**：結構化 JSON/NDJSON，記錄 round_start、success、error、pending、stop。

每次 prompt/response 要記：

- platform
- role / is_archon
- round
- send timestamp
- receive timestamp
- elapsed seconds
- prompt length
- response length
- status
- error reason
- snapshot path

不要只寫自然語言 log。

## 22. snapshot 與 session dump

每次平台錯誤時存：

- full-page screenshot
- HTML
- 當前 URL
- platform
- round
- error type

每場任務結束時存：

- 每個平台的 conversation markdown
- 每個平台的 raw HTML
- 本場 metadata JSON

注意空資料夾不會被 Git 追蹤，所以程式要自己：

```python
os.makedirs("logs/snapshots", exist_ok=True)
os.makedirs("session_dumps", exist_ok=True)
```

## 23. 停止按鈕 / cancel 行為

停止不要直接殺瀏覽器或 abort 已送出的平台 prompt。

比較安全的語義：

- 已送出的 prompt 等自然完成。
- stop 後不再派新的 prompt。
- stop 後不跑 auditor。
- UI 顯示「收尾中」。

原因：硬 abort 可能讓瀏覽器頁面留在生成中、半填入、半送出的狀態，下一場更容易污染。

## 24. 長 prompt 測試建議

長 prompt 是最能測出平台自動化缺陷的場景。

必測：

- 100 字。
- 1,000 字。
- 5,000 字。
- 多行 markdown。
- 表格。
- 中文 + 英文 + code block。

每次送出後檢查：

- readback 是否完整。
- 是否只送出一次。
- 是否被拆成多段。
- response 是否對應當前 prompt。
- log 是否完整保存。

## 25. response 合規性檢查

平台回應不一定可信，尤其在 context 污染時。

可做輕量檢查：

- response 是否等於 prompt echo。
- response 是否包含上一場任務的關鍵詞。
- response 是否包含平台 UI 雜訊，例如「拖放文件」「内容由豆包 AI 生成」。
- response 是否完全無關本輪 prompt。
- response 長度是否過短。

若檢查失敗，不要直接交給 Archon；標記為 suspicious，讓 Archon 知道該回答低可信。

## 26. 平台健康狀態

建議每個平台維護 health state：

```text
READY
BUSY
PENDING
UNAVAILABLE_LOGIN
UNAVAILABLE_CAPTCHA
SUSPICIOUS_RESPONSE
FAILED
```

主流程不要只看字串。尤其不要把 `[PENDING]` 當普通回答直接餵給主持人，除非 prompt 明確告訴主持人該平台不可用。

## 27. 主持人 / Archon 指令解析

自然語言 regex 可以先用，但脆弱。

風險：

- 平台名稱大小寫變形。
- 「所有人」「大家」展開錯。
- 一輪中多個指令解析順序錯。
- 自然語言摘要誤判成指令。

長期建議讓 Archon 輸出嚴格 JSON，例如：

```json
{
  "action": "ask",
  "targets": ["gemini", "chatgpt"],
  "message": "..."
}
```

短期至少要在解析後做 target validation，避免把不存在的平台丟進任務。

## 28. 安全與倫理邊界

這類系統只是接管使用者已登入的本機瀏覽器，不是繞過登入。

文件用詞建議：

- 說「使用已登入的本機 Edge session」。
- 不要說「繞過登入牆」。
- 不要鼓勵破解廣告、跳過 reward、假回報、改 APK、注入、封包攔截。

## 29. PowerShell 專案啟動 SOP

建議做一個 `Start-EdgeCdp.ps1`：

```powershell
[CmdletBinding()]
param(
  [int]$Port = 9222,
  [string]$UserDataDir = "C:\Edge_CDP_Profile",
  [string]$Url = "https://chatgpt.com/",
  [switch]$RestartEdge
)

$edgeCandidates = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $edgeCandidates) {
  throw "Microsoft Edge executable not found."
}

if ($RestartEdge) {
  Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 2
}

$edgePath = $edgeCandidates[0]
Start-Process -FilePath $edgePath -ArgumentList @(
  "--remote-debugging-port=$Port",
  "--user-data-dir=$UserDataDir",
  $Url
)

$deadline = (Get-Date).AddSeconds(30)
do {
  try {
    $version = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
    Write-Host "Edge CDP OK:"
    Write-Host $version.Content
    exit 0
  } catch {
    Start-Sleep -Seconds 1
  }
} while ((Get-Date) -lt $deadline)

throw "Edge CDP did not become available on port $Port."
```

## 30. 最小測試清單

每次改 selector 或流程後，至少跑：

- CDP `/json/version` 可連。
- 找到已登入 tab。
- 開新 tab 可登入。
- 每平台短 prompt 成功。
- 每平台長 prompt readback 成功。
- 每平台送出後 response count 增加。
- 每平台 response 非 prompt echo。
- CAPTCHA 出現時不硬送。
- stop 後不再派新 prompt。
- auditor 能讀完整 log。

## 31. 最重要的三個 must-fix

如果只能先修三件事：

1. **完整 log**：auditor 和 debug 必須使用完整 prompt/response，不可用截斷 log。
2. **login/CAPTCHA hard stop**：偵測到 gate 就標記 unavailable，不硬送 prompt。
3. **新任務新對話**：沿用已登入分頁，但新任務要避免歷史 conversation 污染。

這三件事不做好，多 AI arena 的結果會看起來有輸出，但可信度會很低。
