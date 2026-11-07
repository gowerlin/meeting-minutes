<#
  meeting-minutes 1.0.1 一鍵安裝程式
  - 共用 runtime：%LOCALAPPDATA%\meeting-minutes（Python venv、模型、轉寫腳本、glossary、config）
  - 目標 CLI ：複製 skill 到 %USERPROFILE%\.claude\skills\meeting-minutes（Claude CLI 與桌面版 Code 分頁共用）
  - 目標 App ：在桌面產生上傳用 skill zip（Claude App 對話 / Cowork），並建立右鍵「傳送到 → 會議轉寫（基本版）」
  用法：install.cmd                       互動選單
        install.cmd -Target Both          不詢問，直接安裝（CLI / App / Both）
        install.cmd -Uninstall            解除安裝
  其他參數：-Whisper turbo|large-v3
            -Backend openvino:CPU|openvino:NPU|ct2:cuda（跳過偵測，直接指定）
            -KeepAll（保留所有後端的模型與套件，預設只留選中的）
            -TestRoot <資料夾>（1.0.1；僅供開發測試：runtime、skill、傳送到、桌面都改放到這個資料夾底下）
  硬體只在安裝時偵測一次，結果寫入 config.json；轉寫時不再偵測。換硬體或更新驅動後重新執行即可。
#>
param(
    [ValidateSet("", "CLI", "App", "Both")][string]$Target = "",
    [string]$Whisper = "turbo",
    [string]$Backend = "",
    [switch]$KeepAll,
    [switch]$Uninstall,
    [string]$TestRoot = ""
)

# 原生程式（pip、winget）寫到 stderr 不應中止安裝；檔案操作則一律失敗即停
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["*-Item:ErrorAction"] = "Stop"
$ProgressPreference = "SilentlyContinue"   # PS 5.1 的下載進度條會讓 Invoke-WebRequest 極慢
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Version   = "1.0.1"
$Here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload   = Join-Path $Here "payload"
$MMH       = Join-Path $env:LOCALAPPDATA "meeting-minutes"
$SkillDst  = Join-Path $env:USERPROFILE ".claude\skills\meeting-minutes"
$SendToDir  = [Environment]::GetFolderPath("SendTo")
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$IsTest     = [bool]$TestRoot
if ($IsTest) {
    # 1.0.1：僅供開發測試。所有寫入位置都放到 TestRoot 底下，不碰使用者真正的安裝（runtime、skill、傳送到、桌面）
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
    $TestRoot   = (Resolve-Path -LiteralPath $TestRoot).Path
    $MMH        = Join-Path $TestRoot "home"
    $SkillDst   = Join-Path $TestRoot "skills\meeting-minutes"
    $SendToDir  = Join-Path $TestRoot "SendTo"
    $DesktopDir = Join-Path $TestRoot "Desktop"
    foreach ($d in @($SendToDir, $DesktopDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    $env:MEETING_MINUTES_HOME = $MMH        # 讓 runtime 的 Python 腳本（模型、config.json）也寫到測試位置
}
$VenvPy    = Join-Path $MMH "venv\Scripts\python.exe"
$SendToLnk = Join-Path $SendToDir "會議轉寫（基本版）.lnk"
$LegacyLnk = Join-Path $SendToDir "會議轉寫.lnk"   # 舊版名稱（未標示版本）
$UploadZip = Join-Path $DesktopDir "meeting-minutes-skill-upload.zip"

function Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "    [!] $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "`n[錯誤] $msg" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u;$env:LOCALAPPDATA\Microsoft\WinGet\Links"
}

function Has-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Winget-Install($id, $label) {
    if (-not (Has-Winget)) { Fail "找不到 winget，請手動安裝 $label 後重新執行 install.cmd" }
    Write-Host "    以 winget 安裝 $label ..."
    & winget install --id $id -e --scope user --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        # 有些套件不支援 --scope user，改用預設範圍再試一次
        & winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent
    }
    Refresh-Path
}

function Test-PyVersion($exe, $pre) {
    try {
        $v = & $exe @pre -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(1[0-3])$') { return $true }
    } catch { }
    return $false
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($ver in @("3.12", "3.13", "3.11", "3.10")) {
            if (Test-PyVersion "py" @("-$ver")) { return @{ Exe = "py"; Pre = @("-$ver") } }
        }
    }
    foreach ($cand in @("python",
                        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
        if (($cand -eq "python" -and (Get-Command python -ErrorAction SilentlyContinue)) -or (Test-Path $cand)) {
            if (Test-PyVersion $cand @()) { return @{ Exe = $cand; Pre = @() } }
        }
    }
    return $null
}

function Detect-ClaudeCli { return [bool](Get-Command claude -ErrorAction SilentlyContinue) -or (Test-Path (Join-Path $env:USERPROFILE ".claude")) }
function Detect-ClaudeApp {
    if (Test-Path (Join-Path $env:LOCALAPPDATA "AnthropicClaude")) { return $true }
    try { if (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue) { return $true } } catch { }
    return $false
}

# ------------------------------------------------------------------ uninstall
function Do-Uninstall {
    Step "解除安裝 meeting-minutes"
    if (Test-Path $SkillDst)  { Remove-Item $SkillDst -Recurse -Force; Ok "已移除 Claude CLI skill：$SkillDst" }
    if (Test-Path $SendToLnk) { Remove-Item $SendToLnk -Force; Ok "已移除右鍵「傳送到 → 會議轉寫（基本版）」" }
    if (Test-Path $LegacyLnk) { Remove-Item $LegacyLnk -Force; Ok "已移除舊名稱的右鍵捷徑" }
    if (Test-Path $UploadZip) { Remove-Item $UploadZip -Force; Ok "已移除桌面上的上傳用 zip" }
    if (Test-Path $MMH) {
        $ans = Read-Host "    是否一併刪除 runtime 與模型（$MMH，約 2GB）？[y/N]"
        if ($ans -match '^[yY]') {
            Remove-Item $MMH -Recurse -Force; Ok "已刪除 $MMH"
        } else {
            Warn "保留 $MMH（含 glossary.txt 與模型）"
        }
    }
    Warn "若曾上傳到 Claude App，請到 App 的「自訂 (Customize) → Skills」手動刪除 meeting-minutes。"
    exit 0
}

if ($Uninstall) { Do-Uninstall }

# ------------------------------------------------------------------ menu
if (-not (Test-Path $Payload)) { Fail "找不到 payload 資料夾，請先把整個 zip 解壓縮再執行 install.cmd" }
$hasCli = Detect-ClaudeCli
$hasApp = Detect-ClaudeApp
if (-not $Target) {
    Write-Host ""
    Write-Host "  meeting-minutes $Version 會議記錄 skill 安裝程式" -ForegroundColor White
    Write-Host "  ------------------------------------------------"
    Write-Host ("  偵測：Claude CLI {0}　Claude App {1}" -f ($(if ($hasCli) { "已安裝" } else { "未偵測到" })), ($(if ($hasApp) { "已安裝" } else { "未偵測到" })))
    Write-Host ""
    Write-Host "  [1] Claude CLI（含桌面版 Code 分頁）：本機轉寫 + 自動產出會議記錄"
    Write-Host "  [2] Claude Windows App（對話 / Cowork）：右鍵轉寫 + 上傳 skill 整理會議記錄"
    Write-Host "  [3] 兩者都裝（建議）"
    Write-Host "  [4] 解除安裝"
    Write-Host "  [Q] 離開"
    $sel = Read-Host "`n  請選擇"
    switch -Regex ($sel) {
        '^1$' { $Target = "CLI" }
        '^2$' { $Target = "App" }
        '^3$' { $Target = "Both" }
        '^4$' { Do-Uninstall }
        default { exit 0 }
    }
}
$doCli = $Target -in @("CLI", "Both")
$doApp = $Target -in @("App", "Both")

New-Item -ItemType Directory -Force -Path $MMH | Out-Null
# 1.0.1：讀檔或查詢的 cmdlet 加 -ErrorAction Stop。非終止錯誤 try/catch 抓不到，會在主控台印紅字（比照 Pro 2.0.1）
try { Start-Transcript -Path (Join-Path $MMH "install.log") -Force -ErrorAction Stop | Out-Null } catch { }
if ($IsTest) { Warn "測試模式（-TestRoot）：所有檔案寫到 $TestRoot" }

# ------------------------------------------------------------------ prerequisites
if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
    Fail "目前不支援 ARM64 Windows（Snapdragon）：OpenVINO 與 CUDA 後端都沒有 ARM64 套件"
}
$gpuNames = @()
try { $gpuNames = @(Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object { $_.Name }) } catch { }
$hasNvidia = [bool]($gpuNames | Where-Object { $_ -match "NVIDIA" })

Step "檢查 Python（3.10 ~ 3.13）"
$py = Find-Python
if (-not $py) {
    Winget-Install "Python.Python.3.12" "Python 3.12"
    $py = Find-Python
    if (-not $py) { Fail "Python 安裝後仍找不到，請重開終端機後再執行一次 install.cmd" }
}
$pyExe = $py.Exe; $pyPre = $py.Pre
Ok ("使用 {0} {1}" -f $pyExe, ($pyPre -join " "))

Step "檢查 ffmpeg"
Refresh-Path
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Winget-Install "Gyan.FFmpeg" "ffmpeg"
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Fail "ffmpeg 安裝後仍找不到，請重開終端機（或登出再登入）後再執行一次 install.cmd"
    }
}
Ok "ffmpeg：$((Get-Command ffmpeg).Source)"

# ------------------------------------------------------------------ runtime
Step "安裝 runtime $Version 到 $MMH"
$scriptsDst = Join-Path $MMH "scripts"
if (Test-Path $scriptsDst) { Remove-Item $scriptsDst -Recurse -Force }   # 清掉舊版殘留腳本
Copy-Item (Join-Path $Payload "runtime\scripts") $MMH -Recurse -Force
Copy-Item (Join-Path $Payload "runtime\mm-sendto.ps1") $MMH -Force
Copy-Item (Join-Path $Payload "runtime\requirements.txt") $MMH -Force
Copy-Item (Join-Path $Payload "runtime\requirements-cuda.txt") $MMH -Force
Copy-Item (Join-Path $Here "README.md") $MMH -Force
Copy-Item (Join-Path $Here "THIRD-PARTY-NOTICES.md") $MMH -Force
$gloss = Join-Path $MMH "glossary.txt"
if (-not (Test-Path $gloss)) { Copy-Item (Join-Path $Payload "runtime\glossary.txt") $gloss; Ok "已建立 glossary.txt（可自行編輯專有名詞）" }
else { Ok "保留既有的 glossary.txt" }

if ((Test-Path $VenvPy) -and -not (Test-PyVersion $VenvPy @())) {
    Warn "既有 venv 版本不符，重新建立"
    Remove-Item (Join-Path $MMH "venv") -Recurse -Force
}
if (-not (Test-Path $VenvPy)) {
    & $pyExe @pyPre -m venv (Join-Path $MMH "venv")
    if ($LASTEXITCODE -ne 0) { Fail "建立 venv 失敗" }
}
& $VenvPy -m pip install -U pip --disable-pip-version-check -q
& $VenvPy -m pip install -U -r (Join-Path $MMH "requirements.txt") --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "安裝 Python 套件失敗，詳見 $MMH\install.log" }
Ok "基本套件安裝完成（OpenVINO：Intel NPU / Intel GPU / 任何 x86-64 CPU）"

$cudaInstalled = $false
if ($hasNvidia) {
    Step "偵測到 NVIDIA 顯示卡，安裝 CUDA 後端（faster-whisper + cuBLAS/cuDNN，約 1GB）"
    & $VenvPy -m pip install -U -r (Join-Path $MMH "requirements-cuda.txt") --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) { $cudaInstalled = $true; Ok "CUDA 後端套件安裝完成" }
    else { Warn "CUDA 後端安裝失敗，將只使用 OpenVINO" }
}
$others = @($gpuNames | Where-Object { $_ -notmatch "Intel|NVIDIA|Microsoft" })
if ($others.Count -gt 0) { Warn ("下列顯示卡目前沒有對應後端，不會使用：" + ($others -join "、")) }

Step "硬體偵測、下載模型與實測（只在安裝時進行一次）"
$sbArgs = @((Join-Path $MMH "scripts\setup_backend.py"), "--whisper", $Whisper)
if ($Backend) { $sbArgs += @("--force", $Backend) }
if ($KeepAll) { $sbArgs += "--keep-all" }
$sbOut = @()
& $VenvPy @sbArgs | Tee-Object -Variable sbOut
if ($LASTEXITCODE -ne 0) { Fail "硬體偵測或模型下載失敗（需可連線 huggingface.co 與 github.com），詳見 $MMH\install.log" }
$choice = $null
try { $choice = ($sbOut | Select-Object -Last 1) | ConvertFrom-Json } catch { }
if ($choice -and $choice.prune_ct2_packages -and $cudaInstalled) {
    Write-Host "    CUDA 後端未被選用，移除其套件以節省空間 ..."
    & $VenvPy -m pip uninstall -y faster-whisper ctranslate2 nvidia-cublas-cu12 nvidia-cudnn-cu12 --disable-pip-version-check | Out-Null
}

Step "建立右鍵「傳送到 → 會議轉寫（基本版）」"
if (Test-Path $LegacyLnk) { Remove-Item $LegacyLnk -Force; Ok "已移除舊名稱「會議轉寫」的捷徑（改為標示版本的名稱）" }
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($SendToLnk)
$lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$MMH\mm-sendto.ps1`""
$lnk.WorkingDirectory = $MMH
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,103"
$lnk.Description = "會議轉寫（基本版）：本機轉寫會議錄音／錄影（meeting-minutes）"
$lnk.Save()
Ok "對錄音或錄影檔按右鍵 → 傳送到 → 會議轉寫（基本版）"

# ------------------------------------------------------------------ targets
if ($doCli) {
    Step "安裝到 Claude CLI：$SkillDst"
    if (Test-Path $SkillDst) {
        $bak = Join-Path $MMH ("backup\skill-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        New-Item -ItemType Directory -Force -Path (Split-Path $bak) | Out-Null
        Move-Item $SkillDst $bak
        Ok "舊版已備份到 $bak"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $SkillDst) | Out-Null
    Copy-Item (Join-Path $Payload "skill\meeting-minutes") $SkillDst -Recurse -Force
    Ok "完成。Claude CLI 或桌面版 Code 分頁新開的 session 即可使用"
}

if ($doApp) {
    Step "準備 Claude App 上傳檔"
    Copy-Item (Join-Path $Payload "meeting-minutes-upload.zip") $UploadZip -Force
    Ok "已放到桌面：$UploadZip"
    Write-Host "    請在 Claude App：左側「自訂 (Customize)」→「Skills」→「+」→「Create skill」→「Upload a skill」，選擇上面的 zip。"
    Write-Host "    （需在「設定 → Capabilities」開啟程式碼執行。網頁版：https://claude.ai/customize/skills）"
    if (-not $IsTest) { Start-Process explorer.exe "/select,`"$UploadZip`"" }
}

# ------------------------------------------------------------------ summary
Step "安裝完成（meeting-minutes $Version）"
$cfgPath = Join-Path $MMH "config.json"
$cfg = $null
if (Test-Path -LiteralPath $cfgPath) {
    try { $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json } catch { }
}
Write-Host "    runtime ：$MMH"
if ($cfg) { Write-Host "    選定後端：$($cfg.backend) / $($cfg.device) / $($cfg.compute_type)　模型：$($cfg.whisper)" }
else { Warn "讀不到 $cfgPath，請重新執行 install.cmd 重新偵測硬體" }
Write-Host "    （硬體或驅動變更後，重新執行 install.cmd 即可重新偵測）"
Write-Host "    專有名詞：$gloss"
if ($doCli) { Write-Host "    CLI 用法：在 Claude CLI 說「用 meeting-minutes 整理 D:\會議\0912.mp4，與會 5 人」" }
if ($doApp) { Write-Host "    App 用法：右鍵轉寫 → 把 transcript.md 附到 Claude App →「整理成會議記錄」" }
if ($doCli -and $doApp) {
    Warn "若 Claude CLI 以 claude.ai 帳號登入，上傳到 App 的 skill 也會同步到 CLI；看到兩個 meeting-minutes 時，兩者內容相同，用哪個都可以。"
}
try { Stop-Transcript | Out-Null } catch { }
