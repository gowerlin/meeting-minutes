<#
  會議記錄校稿 1.0.0 安裝程式（Windows；meeting-minutes-pro 的附屬工具，不需要系統管理員）
  - 需要先安裝 meeting-minutes-pro 2.2.0 以上（偵測 %LOCALAPPDATA%\meeting-minutes-pro，或環境變數 MEETING_MINUTES_PRO_HOME）
  - 把程式複製到 <Pro 的資料夾>\proofread\app（升級時整個換新；最近的稿清單 state\ 與 config.json 保留）
  - 建立右鍵「傳送到 → 會議記錄校稿」與「會議記錄校稿.mmproof」的雙擊開啟（只寫目前使用者的登錄 HKCU）
  - 不安裝任何套件：用 Pro 已裝好的 Python（只用標準函式庫）
  用法：install.cmd                       安裝或升級
  其他參數：-TestRoot <資料夾>（僅供開發測試：Pro 的資料夾、傳送到、登錄都改到測試位置，不碰使用者真正的安裝）
  結束代碼：0 完成；2 沒有 Pro、Pro 太舊或不相容（沒有寫入任何檔案）；1 其他錯誤
#>
param(
    [string]$TestRoot = ""
)

# 原生程式（python）寫到 stderr 不應中止安裝；檔案與登錄操作則一律失敗即停
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["*-Item:ErrorAction"] = "Stop"
$PSDefaultParameterValues["*-ItemProperty:ErrorAction"] = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"      # 不在 Pro 的 scripts\ 與本程式資料夾留下 __pycache__

$Version  = "1.0.0"
$MinPro   = "2.2.0"
$ToolName = "會議記錄校稿"
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppSrc   = Join-Path $Here "payload\app"
$ProgId   = "MeetingMinutes.Proofread"
$IconRef  = "$env:SystemRoot\System32\imageres.dll,290"   # 系統內建的「文件＋筆」圖示（同 Pro 用系統圖示的做法）

if ($env:MEETING_MINUTES_PRO_HOME) { $MMH = $env:MEETING_MINUTES_PRO_HOME }
else { $MMH = Join-Path $env:LOCALAPPDATA "meeting-minutes-pro" }
$SendToDir = [Environment]::GetFolderPath("SendTo")
$RegRoot   = "HKCU:\Software\Classes"
$IsTest    = [bool]$TestRoot
if ($IsTest) {
    # 僅供開發測試：Pro 的資料夾同 Pro 的測試模式（<TestRoot>\home）；登錄寫在 HKCU\Software\Classes\ 下的測試鍵，
    # 不是真的副檔名關聯
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
$VenvPyw   = Join-Path $MMH "venv\Scripts\pythonw.exe"
$VenvPy    = Join-Path $MMH "venv\Scripts\python.exe"
$Launcher  = Join-Path $AppDst "mmproof_launcher.py"
$SendToLnk = Join-Path $SendToDir "$ToolName.lnk"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }
function Stop-With([int]$code, $msg) { Write-Host "`n[錯誤] $msg" -ForegroundColor Red; exit $code }

function Write-Utf8NoBom([string]$path, [string]$text) {
    # Python 用 utf-8 讀 JSON：不能有 BOM（PowerShell 5.1 的 Set-Content -Encoding UTF8 會加 BOM）
    [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
}

function Copy-Tree([string]$src, [string]$dst) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $src -Force) {
        if ($item.Name -eq "__pycache__") { continue }
        $to = Join-Path $dst $item.Name
        if ($item.PSIsContainer) { Copy-Tree $item.FullName $to }
        else { Copy-Item -LiteralPath $item.FullName -Destination $to -Force }
    }
}

# ------------------------------------------------------------------ 1. 偵測 Pro（規格 §2.2）
Step "檢查 meeting-minutes-pro"
if (-not (Test-Path -LiteralPath (Join-Path $AppSrc "mmproof_launcher.py"))) {
    Stop-With 1 "找不到安裝檔 payload\app。請先把下載的 zip 完整解壓縮，再執行解開後資料夾裡的 install.cmd"
}
$need = @((Join-Path $MMH "config.json"), (Join-Path $MMH "scripts\common.py"), $VenvPyw, $VenvPy)
$lacking = @($need | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($lacking.Count -gt 0) {
    Stop-With 2 "請先安裝 meeting-minutes-pro $MinPro 以上。安裝方法見 meeting-minutes Portal 的「安裝」頁。（找不到 $MMH 裡的 Pro）"
}
# 版號與介面檢查：用 Pro 的 Python 執行這個安裝包裡的檢查程式（只讀，不寫任何檔）
$env:MEETING_MINUTES_PRO_HOME = $MMH
$out = @(& $VenvPy -B (Join-Path $AppSrc "mmproof_pro.py") --check --home $MMH 2>$null)
$code = $LASTEXITCODE
$res = $null
foreach ($line in ($out | Select-Object -Last 3)) {
    if ([string]$line -match '^\s*\{') { try { $res = [string]$line | ConvertFrom-Json } catch { } }
}
if (-not $res) { Stop-With 2 "無法檢查 meeting-minutes-pro（Pro 的 Python 回報 exit $code）。請重新執行 Pro 的安裝程式後再試一次" }
if (-not $res.ok) { Stop-With 2 ([string]$res.message) }
$ProVersion = [string]$res.version
Ok "meeting-minutes-pro $ProVersion（最低 $MinPro；介面檢查通過）"

# ------------------------------------------------------------------ 2. 停止執行中的舊服務（先讓分頁存檔）
if (Test-Path -LiteralPath (Join-Path $StateDir "instance.json")) {
    Step "停止執行中的會議記錄校稿服務"
    $sd = @(& $VenvPy -B (Join-Path $AppSrc "mmproof_launcher.py") --shutdown --home $MMH 2>$null)
    $st = $null
    try { $st = [string]($sd | Select-Object -Last 1) | ConvertFrom-Json } catch { }
    if ($st -and $st.running -and -not $st.stopped) { Warn "服務沒有在時限內結束；安裝繼續，下次開啟會改用新版" }
    elseif ($st -and $st.running) { Ok "已停止（開著的分頁已先存檔）" }
    else { Ok "沒有執行中的服務" }
}

# ------------------------------------------------------------------ 3. 複製程式（升級：換掉 app\，保留 state\ 與 config.json）
Step "安裝會議記錄校稿 $Version 到 $Dst"
$upgrade = Test-Path -LiteralPath (Join-Path $Dst "version.json")
try {
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    if (Test-Path -LiteralPath $AppDst) { Remove-Item -LiteralPath $AppDst -Recurse -Force }
    Copy-Tree $AppSrc $AppDst
    foreach ($u in @("uninstall.ps1", "uninstall.sh")) {
        $s = Join-Path $Here $u
        if (Test-Path -LiteralPath $s) { Copy-Item -LiteralPath $s -Destination (Join-Path $Dst $u) -Force }
    }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $vj = [ordered]@{ version = $Version; installed_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"); pro_version_at_install = $ProVersion }
    Write-Utf8NoBom (Join-Path $Dst "version.json") (($vj | ConvertTo-Json) + "`n")
} catch {
    Stop-With 1 "複製檔案失敗：$($_.Exception.Message)"
}
if ($upgrade) { Ok "已升級（最近的稿清單與各輸出資料夾的校稿進度都保留）" } else { Ok "已安裝" }

# ------------------------------------------------------------------ 4. 右鍵「傳送到 → 會議記錄校稿」
Step "建立右鍵「傳送到 → $ToolName」"
try {
    New-Item -ItemType Directory -Force -Path $SendToDir | Out-Null
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($SendToLnk)
    $lnk.TargetPath = $VenvPyw                    # pythonw.exe：沒有命令列視窗
    $lnk.Arguments = "-B `"$Launcher`""
    $lnk.WorkingDirectory = $MMH
    $lnk.IconLocation = $IconRef
    $lnk.Description = "$ToolName：校對會議逐字稿（meeting-minutes-pro 的附屬工具）"
    $lnk.Save()
} catch {
    Stop-With 1 "建立右鍵捷徑失敗：$($_.Exception.Message)"
}
Ok "對會議的輸出資料夾（<檔名>_minutes）按右鍵 → 傳送到 → $ToolName"

# ------------------------------------------------------------------ 5. 「.mmproof」雙擊開啟（HKCU，不需要系統管理員）
Step "建立「$ToolName.mmproof」的雙擊開啟"
$openCmd = "`"$VenvPyw`" -B `"$Launcher`" `"%1`""
try {
    $ext = Join-Path $RegRoot ".mmproof"
    $pid_ = Join-Path $RegRoot $ProgId
    foreach ($k in @($ext, $pid_, "$pid_\DefaultIcon", "$pid_\shell\open\command")) {
        if (-not (Test-Path -LiteralPath $k)) { New-Item -Path $k -Force | Out-Null }
    }
    Set-ItemProperty -LiteralPath $ext -Name "(default)" -Value $ProgId
    Set-ItemProperty -LiteralPath $pid_ -Name "(default)" -Value $ToolName
    Set-ItemProperty -LiteralPath "$pid_\DefaultIcon" -Name "(default)" -Value $IconRef
    Set-ItemProperty -LiteralPath "$pid_\shell\open\command" -Name "(default)" -Value $openCmd
} catch {
    Stop-With 1 "寫入檔案關聯失敗：$($_.Exception.Message)"
}
if (-not $IsTest) {
    # 通知檔案總管關聯已變更（失敗也沒關係：重新登入後生效）
    try {
        Add-Type -Namespace MMProof -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);' -ErrorAction Stop
        [MMProof.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch { }
}
Ok "第一次開啟某份稿後，輸出資料夾裡會出現「$ToolName.mmproof」，之後雙擊它就能接著校"

# ------------------------------------------------------------------ 6. 完成
Step "安裝完成（$ToolName $Version，搭配 meeting-minutes-pro $ProVersion）"
Write-Host "    開啟方式：對會議的輸出資料夾（<檔名>_minutes）按右鍵 → 傳送到 → $ToolName；"
Write-Host "              或雙擊輸出資料夾裡的「$ToolName.mmproof」。瀏覽器會自動開啟校稿頁，不需要打任何指令。"
Write-Host "    校稿進度存在各輸出資料夾的 .proofread\，關掉再開會接著校。"
if ([version]($ProVersion -replace '[^0-9.].*$', '') -lt [version]"2.3.0") {
    Write-Host "    「用定稿重做會議記錄」需要 meeting-minutes-pro 2.3.0 以上；目前的 $ProVersion 可以校稿、定稿與經驗匯入。"
}
Write-Host "    使用說明：安裝包裡的 README.md，或 meeting-minutes Portal 的「會議記錄校稿」使用方法頁。"
Write-Host "    移除：執行安裝包裡的 uninstall.cmd（或 $Dst\uninstall.ps1）。"
Write-Host "    要移除 meeting-minutes-pro 時：Pro 2.3.0 以上會自動先移除會議記錄校稿；Pro 2.2.x 請先移除會議記錄校稿。"
if ($IsTest) { Warn "測試模式（-TestRoot）：所有檔案寫到 $TestRoot" }
exit 0
