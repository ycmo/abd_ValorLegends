param(
    [string]$OutputDir = ".\vision_platform\ads\hard_negative_mining\batch_full_40",
    [int]$MaxScreens = 40,
    [double]$ScanScale = 0.35,
    [int]$MaxCandidatesPerScreen = 8,
    [int]$MaxTotal = 300,
    [int]$ContactSheetLimit = 120,
    [int]$Workers = 4
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$Python = Join-Path $ProjectRoot ".venv-codex\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}

Push-Location $ProjectRoot
try {
    Write-Host "[1/2] Mining hard negatives -> $OutputDir"
    & $Python .\vision_platform\ads\tools\mine_hard_negatives.py `
        --output-dir $OutputDir `
        --max-screens $MaxScreens `
        --scan-scale $ScanScale `
        --max-candidates-per-screen $MaxCandidatesPerScreen `
        --max-total $MaxTotal `
        --contact-sheet-limit $ContactSheetLimit

    Write-Host "[2/2] Updating Vision Asset Inventory"
    & $Python .\vision_platform\vision_assets\tools\inventory_images.py `
        --project-root $ProjectRoot `
        --config vision_platform\vision_assets\inventory\scan_sources.json `
        --workers $Workers

    Write-Host ""
    Write-Host "Done."
    Write-Host "Review command:"
    Write-Host ".\.venv-codex\Scripts\python.exe .\vision_platform\vision_assets\review_gui.py --config .\vision_platform\vision_assets\review_gui_hard_negative_config.json"
    Write-Host ""
    Write-Host "If needed, use the left Search box with:"
    Write-Host (Split-Path $OutputDir -Leaf)
}
finally {
    Pop-Location
}
