"""
edge_cdp_ai.py
--------------
Edge CDP AI 分析客戶端。

用途：開發階段 template discovery 輔助工具。
      把 debug screenshot 送給 AI（ChatGPT / Gemini）分析，
      取回 UI 元素候選清單（bbox / label）。

核心邊界：
  ✅ 只分析截圖，回傳候選資料（JSON）
  ✅ CDP 不通時清楚提示使用者，不硬跑
  ✅ login / CAPTCHA 偵測到就標記 unavailable，不送 prompt
  ✅ 保存完整 prompt / raw response log
  ❌ 不控制遊戲、不呼叫 ADB、不自動 promote template
  ❌ 不被正式 bot loop import

依賴：
  pip install playwright
  （使用 connect_over_cdp，不需要 playwright install 下載瀏覽器）

Edge 啟動方式：
  tools/start_edge_cdp.ps1
  或參閱 docs/EDGE_CDP_AI_AUTOMATION_GUIDE.md
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ── 嘗試 import Playwright（graceful fallback） ──────────────────
_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════
# 常數與設定
# ══════════════════════════════════════════════════════════════════

CDP_URL = "http://127.0.0.1:9222"

# 分析回覆的 JSON 格式規範（送給 AI 的 prompt 中嵌入）
REQUIRED_JSON_SCHEMA = """{
  "status": "ok" | "unsure" | "no_target_found",
  "target_label": "close_button" | "skip_button" | "claim_button" | "unknown",
  "candidates": [
    {
      "label": "close_button",
      "bbox": [x1, y1, x2, y2],
      "center": [x, y],
      "confidence_note": "為何判斷這是 close button 的原因",
      "risk_note": "可能的誤判風險"
    }
  ],
  "notes": []
}"""

ANALYSIS_PROMPT_TEMPLATE = """\
你是一個行動遊戲 UI 元素偵測助手，協助開發者找出截圖中可用的關閉 / 跳過按鈕。

圖片說明：
  - 截圖來自 Android 模擬器（Valor Legends 遊戲或其廣告畫面）
  - screen_type: {screen_type}
  - 目標元素: {target_hint}

請找出截圖中所有可能的 **關閉 / 跳過 / 確認** 按鈕，包括但不限於：
  - X 按鈕（右上角或左上角）
  - Close / ×
  - Skip / Skip Ad
  - Claim / Collect（若廣告結束可領獎）
  - Return / 返回

注意事項：
  - bbox 座標格式為 [x1, y1, x2, y2]（左上、右下）
  - center 格式為 [cx, cy]（中心點）
  - 只回報畫面上「現在可見且可點擊」的元素
  - 若找不到任何目標，status 設為 "no_target_found"
  - 若不確定，status 設為 "unsure"，仍列出候選

重要：只回傳 JSON，不要任何其他文字、不要 markdown 代碼框：
{schema}
"""

# 各平台 CSS selector 設定（可能隨平台更新而失效，需要定期維護）
PLATFORM_CONFIG: dict[str, dict[str, Any]] = {
    "chatgpt": {
        "new_chat_url": "https://chatgpt.com/",
        "login_selectors": [
            "a[href*='/auth/login']",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
        ],
        "captcha_selectors": [
            "#challenge-form",
            ".cf-turnstile",
            "[id*='captcha' i]",
        ],
        "input_selectors": [
            "#prompt-textarea",
            "div[id='prompt-textarea']",
            "textarea[placeholder*='message' i]",
        ],
        "send_selectors": [
            "button[data-testid='send-button']",
            "button[aria-label*='Send' i]",
            "button[aria-label*='送' i]",
        ],
        "stop_selectors": [
            "button[data-testid='stop-button']",
            "button[aria-label*='Stop' i]",
            "button[aria-label*='停止' i]",
        ],
        "response_selectors": [
            "[data-message-author-role='assistant']",
            ".markdown.prose",
        ],
        "file_input_selector": "input[type='file'][accept*='image'], input[type='file']",
        "attachment_btn_selectors": [
            "button[aria-label*='Attach' i]",
            "button[aria-label*='Upload' i]",
            "label[for*='file' i]",
            "button:has-text('+')",
        ],
    },
    "gemini": {
        "new_chat_url": "https://gemini.google.com/app",
        "login_selectors": [
            "a[href*='accounts.google.com']",
            "a:has-text('Sign in')",
            "button:has-text('Sign in')",
        ],
        "captcha_selectors": [
            ".captcha-container",
            "#captcha",
            "iframe[title*='captcha' i]",
        ],
        "input_selectors": [
            "div[contenteditable='true'][aria-label*='message' i]",
            "rich-textarea div[contenteditable='true']",
            "textarea",
        ],
        "send_selectors": [
            "button[aria-label*='Send message' i]",
            "button[aria-label*='Send' i]",
            "button.send-button",
            "button[jsname*='send' i]",
        ],
        "stop_selectors": [
            "button[aria-label*='Stop' i]",
        ],
        "response_selectors": [
            "model-response .response-container-content",
            ".response-container",
            "div[data-response-index]",
        ],
        "file_input_selector": "input[type='file']",
        "attachment_btn_selectors": [
            "button[aria-label*='Upload' i]",
            "button[aria-label*='Attach' i]",
            "button[aria-label*='Add image' i]",
        ],
    },
}


# ══════════════════════════════════════════════════════════════════
# 狀態定義
# ══════════════════════════════════════════════════════════════════

class CdpStatus(str, Enum):
    READY               = "ready"
    UNAVAILABLE_NO_CDP  = "unavailable_no_cdp"    # CDP port 不通
    UNAVAILABLE_LOGIN   = "unavailable_login"      # 偵測到未登入狀態
    UNAVAILABLE_CAPTCHA = "unavailable_captcha"    # 偵測到 CAPTCHA
    PARSE_FAILED        = "parse_failed"           # AI 回覆非有效 JSON
    TIMEOUT             = "timeout"               # 等待回覆超時
    FAILED              = "failed"                # 其他錯誤


@dataclass
class AnalysisResult:
    """AI 分析結果的標準化結構。"""
    status: CdpStatus
    provider: str
    screenshot_path: str
    target_hint: str
    screen_type: str

    parsed: Optional[dict] = None      # AI 回傳且成功解析的 JSON
    raw_response: str = ""             # AI 的原始文字回覆
    prompt: str = ""                   # 送出的 prompt
    error: str = ""                    # 若失敗，記錄原因
    session_id: str = ""               # 本次 session 識別碼
    log_path: str = ""                 # 完整 log 儲存路徑
    elapsed_seconds: float = 0.0


# ══════════════════════════════════════════════════════════════════
# CDP 連線檢查（不依賴 Playwright）
# ══════════════════════════════════════════════════════════════════

def check_cdp(cdp_url: str = CDP_URL) -> bool:
    """
    檢查 Edge CDP 是否可用。
    不需要 Playwright，直接用 urllib 請求 /json/version。
    回傳 True 表示可用。
    """
    try:
        req = urllib.request.Request(
            f"{cdp_url}/json/version",
            headers={"User-Agent": "TemplateDiscovery/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return "Browser" in data
    except Exception:
        return False


def print_cdp_startup_hint(cdp_url: str = CDP_URL) -> None:
    """CDP 不通時輸出詳細啟動說明。"""
    print("\n" + "─" * 60)
    print("[EdgeCDP] ❌ 無法連線 CDP：" + cdp_url)
    print("─" * 60)
    print("請先啟動 Edge 並開啟 CDP remote debugging port：\n")
    print("  方法 A：使用 PowerShell 腳本")
    print("    .\\tools\\start_edge_cdp.ps1\n")
    print("  方法 B：手動啟動（PowerShell）")
    print(r'    $Edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"')
    print(r'    & $Edge --remote-debugging-port=9222 --user-data-dir="C:\Edge_CDP_Profile" `')
    print(r'           "https://chatgpt.com/"')
    print()
    print("  啟動後驗證：")
    print("    Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version\n")
    print("  注意：Edge 必須用 CDP profile 啟動，且已在目標 AI 網站登入。")
    print("  參閱：docs/EDGE_CDP_AI_AUTOMATION_GUIDE.md")
    print("─" * 60 + "\n")


# ══════════════════════════════════════════════════════════════════
# AI 分析客戶端
# ══════════════════════════════════════════════════════════════════

class EdgeCdpAiAnalyzer:
    """
    透過 Edge CDP + Playwright 把截圖送給 AI 分析，
    回傳 UI 元素候選資料（供 template discovery 使用）。
    """

    def __init__(
        self,
        provider: str = "chatgpt",
        cdp_url: str = CDP_URL,
        log_dir: str = "data/template_discovery/ai_logs",
        response_timeout: int = 120,
        stable_duration: float = 3.0,
        empty_timeout: int = 20,
    ):
        """
        Parameters
        ----------
        provider : str
            "chatgpt" 或 "gemini"
        cdp_url : str
            Edge CDP endpoint，預設 http://127.0.0.1:9222
        log_dir : str
            AI prompt / response 的完整 log 輸出目錄
        response_timeout : int
            等待 AI 回覆的最大秒數
        stable_duration : float
            文字穩定多少秒才算完成
        empty_timeout : int
            送出後幾秒內沒看到生成開始視為逾時
        """
        if provider not in PLATFORM_CONFIG:
            raise ValueError(f"不支援的 provider: {provider!r}，可用: {list(PLATFORM_CONFIG.keys())}")

        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright 未安裝。請執行：\n"
                "  pip install playwright\n"
                "（不需要 playwright install，因為直接 connect_over_cdp 到既有 Edge）"
            )

        self.provider = provider
        self.cdp_url = cdp_url
        self.log_dir = log_dir
        self.response_timeout = response_timeout
        self.stable_duration = stable_duration
        self.empty_timeout = empty_timeout
        self.cfg = PLATFORM_CONFIG[provider]
        os.makedirs(log_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def analyze(
        self,
        screenshot_path: str,
        target_hint: str = "close_button",
        screen_type: str = "ad_interstitial",
    ) -> AnalysisResult:
        """
        把截圖送給 AI 分析，回傳標準化 AnalysisResult。

        步驟：
          1. 確認 CDP 可用
          2. 連線到 Edge（既有 session）
          3. 開新對話（避免上下文污染）
          4. 偵測 login / CAPTCHA gate
          5. 上傳截圖 + 送出 prompt
          6. 等待回覆穩定
          7. 解析 JSON
          8. 儲存完整 log

        Parameters
        ----------
        screenshot_path : str
            要分析的截圖路徑（本地絕對或相對路徑）
        target_hint : str
            告訴 AI 要找什麼，例如 "close_button"、"skip_button"
        screen_type : str
            截圖類型，例如 "ad_interstitial"、"ad_endcard"、"unknown"
        """
        session_id = f"ai_{time.strftime('%Y%m%d_%H%M%S')}"
        t_start = time.time()

        result = AnalysisResult(
            status=CdpStatus.FAILED,
            provider=self.provider,
            screenshot_path=screenshot_path,
            target_hint=target_hint,
            screen_type=screen_type,
            session_id=session_id,
        )

        # ① 檢查截圖存在
        if not os.path.exists(screenshot_path):
            result.error = f"截圖不存在: {screenshot_path!r}"
            print(f"[EdgeCDP] ❌ {result.error}")
            self._save_log(session_id, result)
            return result

        # ② 檢查 CDP
        if not check_cdp(self.cdp_url):
            result.status = CdpStatus.UNAVAILABLE_NO_CDP
            result.error = "CDP 不可用"
            print_cdp_startup_hint(self.cdp_url)
            self._save_log(session_id, result)
            return result

        # ③ Playwright 流程
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(self.cdp_url)
                print(f"[EdgeCDP] 已連線到 Edge CDP ({self.provider})")

                page = self._get_or_create_page(browser)

                # ④ 開新對話
                print(f"[EdgeCDP] 導向新對話: {self.cfg['new_chat_url']}")
                page.goto(self.cfg["new_chat_url"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                # ⑤ 偵測 auth gate
                gate_status = self._detect_auth_gate(page)
                if gate_status is not None:
                    result.status = gate_status
                    result.error = f"Auth gate 偵測到: {gate_status.value}"
                    print(f"[EdgeCDP] ⚠️  {result.error}")
                    print("[EdgeCDP] 請手動在 Edge 中登入後重試。")
                    self._save_snapshot(page, session_id, "auth_gate")
                    self._save_log(session_id, result)
                    return result

                # ⑥ 建立 prompt
                prompt = ANALYSIS_PROMPT_TEMPLATE.format(
                    screen_type=screen_type,
                    target_hint=target_hint,
                    schema=REQUIRED_JSON_SCHEMA,
                )
                result.prompt = prompt

                # ⑦ 上傳截圖 + 送出 prompt
                send_ok = self._upload_and_send(page, screenshot_path, prompt, session_id)
                if not send_ok:
                    result.error = "無法送出 prompt（輸入框或送出按鈕找不到）"
                    self._save_snapshot(page, session_id, "send_failed")
                    self._save_log(session_id, result)
                    return result

                # ⑧ 等待回覆
                raw = self._wait_response(page)
                result.raw_response = raw

                if raw is None:
                    result.status = CdpStatus.TIMEOUT
                    result.error = "等待 AI 回覆超時"
                    self._save_snapshot(page, session_id, "timeout")
                    self._save_log(session_id, result)
                    return result

                # ⑨ 解析 JSON
                parsed = self._parse_json(raw)
                if parsed is None:
                    result.status = CdpStatus.PARSE_FAILED
                    result.error = "AI 回覆不是有效 JSON，已存 raw response"
                    print(f"[EdgeCDP] ⚠️  JSON 解析失敗，raw response 已保存到 log")
                else:
                    result.status = CdpStatus.READY
                    result.parsed = parsed
                    cand_count = len(parsed.get("candidates", []))
                    print(f"[EdgeCDP] ✅ 解析成功，candidates: {cand_count} 個")

        except PlaywrightTimeoutError as e:
            result.status = CdpStatus.TIMEOUT
            result.error = f"Playwright timeout: {e}"
        except Exception as e:
            result.status = CdpStatus.FAILED
            result.error = f"未預期錯誤: {e}"
            import traceback; traceback.print_exc()

        result.elapsed_seconds = round(time.time() - t_start, 2)
        log_path = self._save_log(session_id, result)
        result.log_path = log_path
        return result

    # ------------------------------------------------------------------
    # 分頁管理
    # ------------------------------------------------------------------

    def _get_or_create_page(self, browser: "Browser") -> "Page":
        """
        尋找已開啟的目標平台分頁；找不到則新建一個分頁。
        沿用分頁可保留登入狀態，但一定要在此後開新對話。
        """
        target_domain = self.cfg["new_chat_url"].split("/")[2]  # e.g. "chatgpt.com"
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if target_domain in pg.url:
                    print(f"[EdgeCDP] 沿用已開啟分頁: {pg.url}")
                    return pg
        # 找不到，建新分頁
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        print(f"[EdgeCDP] 開啟新分頁")
        return page

    # ------------------------------------------------------------------
    # Auth gate 偵測
    # ------------------------------------------------------------------

    def _detect_auth_gate(self, page: "Page") -> Optional[CdpStatus]:
        """
        檢查是否有 login gate 或 CAPTCHA。
        回傳對應 CdpStatus，若正常則回傳 None。
        """
        # Login gate
        for sel in self.cfg.get("login_selectors", []):
            try:
                if page.locator(sel).count() > 0:
                    return CdpStatus.UNAVAILABLE_LOGIN
            except Exception:
                pass

        # CAPTCHA
        for sel in self.cfg.get("captcha_selectors", []):
            try:
                if page.locator(sel).count() > 0:
                    return CdpStatus.UNAVAILABLE_CAPTCHA
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # 上傳截圖 + 送出 prompt
    # ------------------------------------------------------------------

    def _upload_and_send(
        self, page: "Page", screenshot_path: str, prompt: str, session_id: str
    ) -> bool:
        """
        上傳截圖檔案並送出 prompt 文字。
        回傳 True 表示成功觸發送出。
        """
        abs_path = os.path.abspath(screenshot_path)

        # 嘗試上傳圖片（方法 A：先點 attachment 按鈕）
        uploaded = False
        for btn_sel in self.cfg.get("attachment_btn_selectors", []):
            try:
                btn = page.locator(btn_sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(0.8)
                    break
            except Exception:
                pass

        # 找到 file input 並設定檔案（方法 B：直接 set_input_files）
        file_sel = self.cfg.get("file_input_selector", "input[type='file']")
        try:
            file_input = page.locator(file_sel).first
            file_input.set_input_files(abs_path, timeout=5000)
            uploaded = True
            print(f"[EdgeCDP] 圖片已上傳: {os.path.basename(abs_path)}")
            time.sleep(1.5)  # 等待圖片預覽載入
        except Exception as e:
            print(f"[EdgeCDP] ⚠️  圖片上傳失敗: {e}")
            print("[EdgeCDP] 繼續嘗試純文字 prompt（無圖片）")

        # 填入 prompt
        filled = False
        for inp_sel in self.cfg.get("input_selectors", []):
            try:
                inp = page.locator(inp_sel).first
                if not inp.is_visible(timeout=3000):
                    continue

                # 方法 A：locator.fill()
                try:
                    inp.fill(prompt, timeout=5000)
                    filled = True
                    break
                except Exception:
                    pass

                # 方法 B：JS set textContent + dispatch input
                try:
                    page.evaluate(
                        """(args) => {
                            const el = document.querySelector(args.sel);
                            if (!el) return;
                            el.textContent = args.text;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }""",
                        {"sel": inp_sel, "text": prompt},
                    )
                    filled = True
                    break
                except Exception:
                    pass

                # 方法 C：keyboard.insert_text
                try:
                    inp.click()
                    page.keyboard.insert_text(prompt)
                    filled = True
                    break
                except Exception:
                    pass

            except Exception:
                continue

        if not filled:
            print("[EdgeCDP] ❌ 找不到輸入框或填入失敗")
            return False

        # Readback 驗證：檢查 prompt 尾端是否存在
        time.sleep(0.5)
        tail = prompt[-80:].strip()
        readback_ok = False
        for inp_sel in self.cfg.get("input_selectors", []):
            try:
                current = page.locator(inp_sel).first.inner_text(timeout=2000)
                if tail.replace("\n", " ") in current.replace("\n", " "):
                    readback_ok = True
                    break
            except Exception:
                pass

        if not readback_ok:
            print("[EdgeCDP] ⚠️  Readback 驗證失敗（prompt 可能只進去一半），仍繼續送出")

        # 送出
        sent = False
        for send_sel in self.cfg.get("send_selectors", []):
            try:
                btn = page.locator(send_sel).first
                if btn.is_visible(timeout=2000) and btn.is_enabled(timeout=2000):
                    btn.click()
                    sent = True
                    print(f"[EdgeCDP] Prompt 已送出（{len(prompt)} 字）")
                    break
            except Exception:
                continue

        if not sent:
            # 最後嘗試 Enter
            try:
                for inp_sel in self.cfg.get("input_selectors", []):
                    try:
                        page.locator(inp_sel).first.press("Enter")
                        sent = True
                        break
                    except Exception:
                        pass
            except Exception:
                pass

        return sent

    # ------------------------------------------------------------------
    # 等待 AI 回覆
    # ------------------------------------------------------------------

    def _wait_response(self, page: "Page") -> Optional[str]:
        """
        等待 AI 生成完成。
        策略：等 stop button 出現（generation start），
              再等 stop button 消失且文字穩定 stable_duration 秒。
        回傳最後 assistant 訊息文字，timeout 回傳 None。
        """
        stop_selectors = self.cfg.get("stop_selectors", [])
        response_selectors = self.cfg.get("response_selectors", [])

        # 記錄送出前的 response count
        pre_count = self._count_responses(page, response_selectors)

        # 等待 generation start（stop button 出現，或 response count 增加）
        t_start = time.time()
        generation_started = False
        while time.time() - t_start < self.empty_timeout:
            # 檢查 stop button
            for sel in stop_selectors:
                try:
                    if page.locator(sel).is_visible(timeout=500):
                        generation_started = True
                        break
                except Exception:
                    pass
            if generation_started:
                break

            # 或 response count 增加
            cur_count = self._count_responses(page, response_selectors)
            if cur_count > pre_count:
                generation_started = True
                break

            time.sleep(0.8)

        if not generation_started:
            print(f"[EdgeCDP] ⚠️  {self.empty_timeout}s 內未見到生成開始")
            return None

        print("[EdgeCDP] AI 生成中...")

        # 等待生成完成（stop button 消失 + 文字穩定）
        last_text = ""
        stable_since = None
        t_wait_start = time.time()

        while time.time() - t_wait_start < self.response_timeout:
            current_text = self._extract_latest_response(page, response_selectors)

            # 檢查 stop button 是否已消失
            stop_visible = False
            for sel in stop_selectors:
                try:
                    if page.locator(sel).is_visible(timeout=300):
                        stop_visible = True
                        break
                except Exception:
                    pass

            if current_text != last_text:
                last_text = current_text
                stable_since = time.time()
            elif (
                not stop_visible
                and current_text
                and stable_since is not None
                and (time.time() - stable_since) >= self.stable_duration
            ):
                elapsed = round(time.time() - t_wait_start, 1)
                print(f"[EdgeCDP] ✅ AI 回覆完成（{elapsed}s，{len(current_text)} 字）")
                return current_text

            time.sleep(0.8)

        print(f"[EdgeCDP] ⏰ 等待 AI 回覆超時（{self.response_timeout}s）")
        return last_text if last_text else None

    # ------------------------------------------------------------------
    # DOM 工具
    # ------------------------------------------------------------------

    def _count_responses(self, page: "Page", selectors: list) -> int:
        for sel in selectors:
            try:
                return page.locator(sel).count()
            except Exception:
                pass
        return 0

    def _extract_latest_response(self, page: "Page", selectors: list) -> str:
        """取得最後一條 assistant 訊息的文字。"""
        for sel in selectors:
            try:
                items = page.locator(sel)
                count = items.count()
                if count > 0:
                    return items.nth(count - 1).inner_text(timeout=2000)
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------------
    # JSON 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """
        嘗試從 raw response 解析 JSON。
        AI 有時會在 JSON 外包 markdown 代碼框，需要先清理。
        """
        if not raw:
            return None

        # 清理 markdown 代碼框
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines).strip()

        # 嘗試直接解析
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 嘗試找第一個 { ... } 塊
        try:
            start = cleaned.index("{")
            end = cleaned.rindex("}") + 1
            return json.loads(cleaned[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        return None

    # ------------------------------------------------------------------
    # Log / Snapshot
    # ------------------------------------------------------------------

    def _save_log(self, session_id: str, result: "AnalysisResult") -> str:
        """
        儲存完整 prompt / raw response log。
        分 UI log（可截斷）和 full log（不截斷）。
        """
        log_path = os.path.join(self.log_dir, f"{session_id}.json")
        log_data = {
            "session_id": session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "provider": result.provider,
            "screenshot_path": result.screenshot_path,
            "target_hint": result.target_hint,
            "screen_type": result.screen_type,
            "status": result.status.value if isinstance(result.status, CdpStatus) else str(result.status),
            "error": result.error,
            "elapsed_seconds": result.elapsed_seconds,
            "prompt_length": len(result.prompt),
            "prompt": result.prompt,                   # 完整 prompt，不截斷
            "raw_response": result.raw_response,       # 完整回覆，不截斷
            "parsed": result.parsed,
        }
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log_data, f, ensure_ascii=False, indent=2)
            print(f"[EdgeCDP] Log 已儲存: {log_path}")
        except Exception as e:
            print(f"[EdgeCDP] 無法儲存 log: {e}", file=sys.stderr)
        return log_path

    def _save_snapshot(self, page: "Page", session_id: str, tag: str) -> None:
        """儲存 full-page screenshot（error snapshot）。"""
        try:
            snap_path = os.path.join(self.log_dir, f"{session_id}_{tag}.png")
            page.screenshot(path=snap_path, full_page=True)
            print(f"[EdgeCDP] Snapshot 已儲存: {snap_path}")
        except Exception as e:
            print(f"[EdgeCDP] 無法儲存 snapshot: {e}", file=sys.stderr)
