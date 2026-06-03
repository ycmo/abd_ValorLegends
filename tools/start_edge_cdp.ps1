# start_edge_cdp.ps1
# 啟動 Edge 並開啟 CDP remote debugging port。
# 參閱：docs/EDGE_CDP_AI_AUTOMATION_GUIDE.md
#
# 使用方式：
#   .\tools\start_edge_cdp.ps1
#   .\tools\start_edge_cdp.ps1 -Url "https://gemini.google.com/app"
#   .\tools\start_edge_cdp.ps1 -RestartEdge

[CmdletBinding()]
param(
    [int]    $Port        = 9222,
    [string] $UserDataDir = "C:\Edge_CDP_Profile",
    [string] $Url         = "https://chatgpt.com/",
    [switch] $RestartEdge
)

# 找到 Edge 執行檔
$EdgeCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $EdgeCandidates) {
    Write-Error "找不到 Microsoft Edge。請確認 Edge 已安裝。"
    exit 1
}

$EdgePath = $EdgeCandidates[0]
Write-Host "Edge 路徑: $EdgePath"

# 若指定 -RestartEdge，先關閉所有 Edge
if ($RestartEdge) {
    Write-Host "關閉既有 Edge 程序..."
    Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# 啟動 Edge 並開啟 CDP port
Write-Host "啟動 Edge CDP..."
Write-Host "  port       : $Port"
Write-Host "  profile    : $UserDataDir"
Write-Host "  url        : $Url"

Start-Process -FilePath $EdgePath -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$UserDataDir",
    $Url
)

# 輪詢等待 CDP 可用（最多 30 秒）
Write-Host ""
Write-Host "等待 CDP 就緒..."
$Deadline = (Get-Date).AddSeconds(30)
$Ready = $false

do {
    try {
        $Resp = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
        if ($Resp.StatusCode -eq 200) {
            $Ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
        Write-Host "." -NoNewline
    }
} while ((Get-Date) -lt $Deadline)

Write-Host ""

if ($Ready) {
    Write-Host ""
    Write-Host "✅ Edge CDP 已就緒：http://127.0.0.1:$Port"
    Write-Host ""
    Write-Host "驗證指令："
    Write-Host "  Invoke-WebRequest -UseBasicParsing http://127.0.0.1:$Port/json/version"
    Write-Host ""
    Write-Host "重要：請確認已在 Edge 中手動登入目標 AI 網站（ChatGPT / Gemini）。"
    Write-Host "      登入完成後才能執行 ai-analyze。"
    Write-Host ""
    Write-Host "執行 AI 分析："
    Write-Host "  python tools/template_discovery.py ai-analyze --pending-id <ID> --provider chatgpt"
} else {
    Write-Error "❌ Edge CDP 未在 30 秒內就緒，請手動確認 Edge 是否正常啟動。"
    exit 1
}
