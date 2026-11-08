<#
  會議記錄校稿 1.1.0 移除程式（Windows）
  - 停止執行中的服務（開著的分頁先存檔）；刪除程式（proofread\app）、version.json、config.json、移除程式本身、
    右鍵「傳送到 → 會議記錄校稿」與「.mmproof」的雙擊開啟
  - 詢問是否刪除最近的稿清單（proofread\state，預設保留）
  - 不刪除：各輸出資料夾的 .proofread\（校稿進度）、定稿檔、meeting-minutes-pro 的 corrections.tsv、glossary.txt、backups\
  用法：uninstall.cmd（或在 PowerShell 執行這個檔）
  參數：-Quiet（不詢問、不等待：最近的稿清單照預設保留；meeting-minutes-pro 2.3.0 以上解除安裝時這樣呼叫）
        -TestRoot <資料夾>（僅供開發測試，同安裝程式）
  結束代碼：0 完成（或本來就沒有安裝）；1 有項目沒有刪除成功
#>
param(
    [switch]$Quiet,
    [string]$TestRoot = ""
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

$ToolName = "會議記錄校稿"
$ProgId   = "MeetingMinutes.Proofread"
if ($env:MEETING_MINUTES_PRO_HOME) { $MMH = $env:MEETING_MINUTES_PRO_HOME }
else { $MMH = Join-Path $env:LOCALAPPDATA "meeting-minutes-pro" }
$SendToDir = [Environment]::GetFolderPath("SendTo")
$RegRoot   = "HKCU:\Software\Classes"
$IsTest    = [bool]$TestRoot
if ($IsTest) {
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
    $TestRoot  = (Resolve-Path -LiteralPath $TestRoot).Path
    $MMH       = Join-Path $TestRoot "home"
    $SendToDir = Join-Path $TestRoot "SendTo"
    $leaf      = (Split-Path -Leaf $TestRoot) -replace '[^A-Za-z0-9_.-]', '_'
    $RegRoot   = "HKCU:\Software\Classes\MMProofTest\$leaf"
}
$Dst       = Join-Path $MMH "proofread"
$AppDst    = Join-Path $Dst "app"
$StateDir  = Join-Path $Dst "state"
$VenvPy    = Join-Path $MMH "venv\Scripts\python.exe"
$SendToLnk = Join-Path $SendToDir "$ToolName.lnk"
$ExtKey    = Join-Path $RegRoot ".mmproof"
$ProgKey   = Join-Path $RegRoot $ProgId
$script:Errors = 0

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }

function Remove-Path([string]$p, [string]$label) {
    if (-not (Test-Path -LiteralPath $p)) { return }
    try {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
        Ok "已刪除 $label"
    } catch {
        $script:Errors++
        Warn "無法刪除 $label（$p）：$($_.Exception.Message)"
    }
}

Step "移除 $ToolName"
$installed = (Test-Path -LiteralPath $Dst) -or (Test-Path -LiteralPath $SendToLnk) -or (Test-Path -LiteralPath $ProgKey)
if (-not $installed) {
    Ok "沒有安裝 $ToolName（$Dst 不存在），不需要移除"
    exit 0
}

# 1. 停止執行中的服務：請它先讓開著的分頁存檔再結束（規格 §3.8）
if ((Test-Path -LiteralPath (Join-Path $StateDir "instance.json")) -and (Test-Path -LiteralPath (Join-Path $AppDst "mmproof_launcher.py")) -and (Test-Path -LiteralPath $VenvPy)) {
    $env:MEETING_MINUTES_PRO_HOME = $MMH
    $sd = @(& $VenvPy -B (Join-Path $AppDst "mmproof_launcher.py") --shutdown --home $MMH 2>$null)
    $st = $null
    try { $st = [string]($sd | Select-Object -Last 1) | ConvertFrom-Json } catch { }
    if ($st -and $st.running -and -not $st.stopped) { Warn "服務沒有在時限內結束；它會在閒置後自己結束" }
    elseif ($st -and $st.running) { Ok "已停止服務（開著的分頁已先存檔）" }
}

# 2. 程式與設定
Remove-Path $AppDst "程式（proofread\app）"
Remove-Path (Join-Path $Dst "version.json") "version.json"
Remove-Path (Join-Path $Dst "config.json") "config.json"

# 3. 右鍵捷徑與檔案關聯（.mmproof 只在仍指向本工具時才刪）
Remove-Path $SendToLnk "右鍵「傳送到 → $ToolName」"
try {
    if (Test-Path -LiteralPath $ExtKey) {
        $cur = (Get-ItemProperty -LiteralPath $ExtKey -ErrorAction Stop).'(default)'
        if ($cur -eq $ProgId) { Remove-Item -LiteralPath $ExtKey -Recurse -Force -ErrorAction Stop }
    }
    if (Test-Path -LiteralPath $ProgKey) { Remove-Item -LiteralPath $ProgKey -Recurse -Force -ErrorAction Stop }
    if ($IsTest -and (Test-Path -LiteralPath $RegRoot)) {
        Remove-Item -LiteralPath $RegRoot -Recurse -Force -ErrorAction Stop
        $parent = Split-Path -Parent $RegRoot
        if ((Test-Path -LiteralPath $parent) -and -not (Get-ChildItem -LiteralPath $parent)) { Remove-Item -LiteralPath $parent -Force -ErrorAction Stop }
    }
    Ok "已移除「.mmproof」的雙擊開啟"
} catch {
    $script:Errors++
    Warn "無法移除「.mmproof」的關聯：$($_.Exception.Message)"
}
if (-not $IsTest) {
    try {
        Add-Type -Namespace MMProof -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);' -ErrorAction Stop
        [MMProof.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch { }
}

# 4. 最近的稿清單（state\）：預設保留
if (Test-Path -LiteralPath $StateDir) {
    $del = $false
    if (-not $Quiet) {
        $ans = Read-Host "    要刪除最近的稿清單嗎？[y/N]"
        $del = $ans -match '^[yY]'
    }
    if ($del) { Remove-Path $StateDir "最近的稿清單（proofread\state）" }
    elseif ($Quiet) { Ok "保留最近的稿清單（安靜模式，不詢問）：$StateDir" }
    else { Ok "保留最近的稿清單（$StateDir）" }
}

# 5. 移除程式本身（PowerShell 已把這個檔讀進記憶體，刪掉不影響執行）
foreach ($u in @("uninstall.ps1", "uninstall.sh")) { Remove-Path (Join-Path $Dst $u) $u }
if ((Test-Path -LiteralPath $Dst) -and -not (Get-ChildItem -LiteralPath $Dst -Force)) {
    try { Remove-Item -LiteralPath $Dst -Force -ErrorAction Stop } catch { }
}

Write-Host "    沒有刪除：各輸出資料夾的 .proofread\（校稿進度）、定稿檔（transcript.final.*）、"
Write-Host "    meeting-minutes-pro 的 corrections.tsv、glossary.txt 與 backups\。"
if ($script:Errors -gt 0) {
    Warn "有 $($script:Errors) 個項目沒有刪除成功（見上面的訊息）"
    exit 1
}
Ok "已移除 $ToolName"
exit 0
