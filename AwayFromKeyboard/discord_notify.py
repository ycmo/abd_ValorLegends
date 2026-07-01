import json
import urllib.request
import urllib.error
from typing import Optional

# 請替換為你的 Webhook 網址
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1520700364024840273/rbeEcempNQ77h4Maz_rvMgJS-BYI7xRpZrxk9X4Bf1IPHbT55-E7wwfoVir9w48HKpKW"

def send_discord_msg(msg: str):
    """發送訊息至 Discord Webhook"""
    if not DISCORD_WEBHOOK_URL:
        return
        
    data = {
        "content": msg,
        "username": "掛機通報員"
    }
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, 
        data=json.dumps(data).encode('utf-8'), 
        headers=headers
    )
    
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"⚠️ [Discord] 通知發送失敗: {e}")


def format_status_msg(
    source: str,
    status: str,
    *,
    account: Optional[str] = None,
    route: Optional[str] = None,
    detail: Optional[str] = None,
) -> str:
    parts = [f"[{source}]"]
    if account:
        parts.append(str(account))
    if route:
        parts.append(str(route))
    parts.append(str(status))
    if detail:
        parts.append(str(detail))
    return " | ".join(parts)


def notify_status(
    source: str,
    status: str,
    *,
    account: Optional[str] = None,
    route: Optional[str] = None,
    detail: Optional[str] = None,
    enabled: bool = True,
) -> None:
    if not enabled:
        return
    send_discord_msg(
        format_status_msg(
            source,
            status,
            account=account,
            route=route,
            detail=detail,
        )
    )

if __name__ == "__main__":
    send_discord_msg("🚀 **測試連線：Antigravity 系統準備就緒！**\n如果你看到這條訊息，代表監控頻道已經成功開通啦！")
    print("已發送測試訊息，請去 Discord 頻道查看！")
