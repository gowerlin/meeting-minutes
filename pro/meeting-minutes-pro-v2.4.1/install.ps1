<#
  meeting-minutes-pro 2.4.1 一鍵安裝程式
  - 共用 runtime：%LOCALAPPDATA%\meeting-minutes-pro（Python venv、模型、轉寫腳本、glossary、config）
    設定環境變數 MEETING_MINUTES_PRO_HOME 可改放到其他位置
  - 目標 CLI ：複製 skill 到 %USERPROFILE%\.claude\skills\meeting-minutes-pro（Claude CLI 與桌面版 Code 分頁共用）
  - 目標 App ：在桌面產生上傳用 skill zip（Claude App 對話 / Cowork），並建立右鍵「傳送到 → 會議轉寫（Pro）」
  〔2.4.0〕另建右鍵「傳送到 → 會議轉寫（Pro，本機限定）」（機敏會議：不做 AI 校正與整理，輸出資料夾寫入標記檔 local-only.json）；
          config.json 的 privacy.local_only（預設 false；升級時保留既有的值）
  〔2.4.1〕config.json 存在但讀不了（權限、被鎖、不是 UTF-8、不是合法 JSON、空檔、最外層不是物件）時一開始就停下（exit 1），
          不寫任何東西，原檔逐位元不變；請修好或刪掉後重新執行（規格 2.4.1 §3）
  用法：install.cmd                       互動選單
        install.cmd -Target Both          不詢問，直接安裝（CLI / App / Both）
        install.cmd -Uninstall            解除安裝
  其他參數：-Whisper turbo|large-v3
            -Backend openvino:CPU|openvino:NPU|ct2:cuda（跳過偵測，直接指定；後端與裝置和既有設定相同時沿用既有精度，1.2.1）
            -ComputeType int8_float16|float16|int8_float32|…（搭配 -Backend，明確指定精度）
            -KeepAll（保留所有後端的模型與套件，預設只留選中的）
            -Breeze / -NoBreeze（是否安裝 Breeze-ASR-25；不指定時會詢問）
            -Correct / -NoCorrect（在 Claude CLI 對話或命令列轉寫時是否自動校正；不指定時，第一次安裝會詢問一次。
                                  右鍵「傳送到」入口不受影響：1.2.0 起每次轉寫完都會問要不要做 AI 校正與會議摘要）
            -CorrectProvider auto|claude|openai   -CorrectModel <模型>   -CorrectChannel cli|api
            -TestRoot <資料夾>（僅供開發測試：runtime、skill、傳送到、桌面都改放到這個資料夾底下）
  〔2.0.0〕GPU 說話者分離（選用，NVIDIA 顯示卡；pyannote，約 5 GB，權重要自己到 Hugging Face 同意條件並登入）：
            -GpuDiar（不詢問，直接安裝或補完成）　-NoGpuDiar（不安裝、不詢問）　-RemoveGpuDiar（移除 GPU 套件與權重）
            不指定時：偵測到 NVIDIA 顯示卡、而且還沒裝過才會詢問一次（預設不裝）
  硬體只在安裝時偵測一次，結果寫入 config.json；轉寫時不再偵測。換硬體或更新驅動後重新執行即可。
#>
param(
    [ValidateSet("", "CLI", "App", "Both")][string]$Target = "",
    [string]$Whisper = "turbo",
    [string]$Backend = "",
    [string]$ComputeType = "",
    [switch]$KeepAll,
    [switch]$Breeze,
    [switch]$NoBreeze,
    [switch]$Correct,
    [switch]$NoCorrect,
    [ValidateSet("", "auto", "claude", "openai")][string]$CorrectProvider = "",
    [string]$CorrectModel = "",
    [ValidateSet("", "cli", "api")][string]$CorrectChannel = "",
    [switch]$Uninstall,
    [string]$TestRoot = "",
    [switch]$GpuDiar,
    [switch]$NoGpuDiar,
    [switch]$RemoveGpuDiar
)

# 原生程式（pip、winget）寫到 stderr 不應中止安裝；檔案操作則一律失敗即停
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["*-Item:ErrorAction"] = "Stop"
$ProgressPreference = "SilentlyContinue"   # PS 5.1 的下載進度條會讓 Invoke-WebRequest 極慢
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Version   = "2.4.1"
$Here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload   = Join-Path $Here "payload"
if ($env:MEETING_MINUTES_PRO_HOME) { $MMH = $env:MEETING_MINUTES_PRO_HOME }
else { $MMH = Join-Path $env:LOCALAPPDATA "meeting-minutes-pro" }
$SkillDst   = Join-Path $env:USERPROFILE ".claude\skills\meeting-minutes-pro"
$SendToDir  = [Environment]::GetFolderPath("SendTo")
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$IsTest     = [bool]$TestRoot
if ($IsTest) {
    # 僅供開發測試：所有寫入位置都放到 TestRoot 底下，不碰使用者真正的安裝
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
    $TestRoot   = (Resolve-Path -LiteralPath $TestRoot).Path
    $MMH        = Join-Path $TestRoot "home"
    $SkillDst   = Join-Path $TestRoot "skills\meeting-minutes-pro"
    $SendToDir  = Join-Path $TestRoot "SendTo"
    $DesktopDir = Join-Path $TestRoot "Desktop"
    foreach ($d in @($SendToDir, $DesktopDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}
$env:MEETING_MINUTES_PRO_HOME = $MMH        # 讓 runtime 的 Python 腳本與本程式用同一個位置
$VenvPy    = Join-Path $MMH "venv\Scripts\python.exe"
$SendToLnk = Join-Path $SendToDir "會議轉寫（Pro）.lnk"
# 〔2.4.0〕第二個右鍵入口：本機限定（規格 2.4.0 §2.2、§4）。從這裡轉寫的輸出資料夾寫入標記檔 local-only.json，這份之後都不送雲端
$SendToLnkLocal = Join-Path $SendToDir "會議轉寫（Pro，本機限定）.lnk"
$LegacyLnk = Join-Path $SendToDir "會議轉寫 Pro.lnk"   # 舊版名稱（未標示版本）
$UploadZip = Join-Path $DesktopDir "meeting-minutes-pro-skill-upload.zip"
# 〔2.0.0〕GPU 說話者分離（獨立 venv＋本機權重；規格 §4.2、§8）與自訂範本目錄（§3.8）
$GpuVenv     = Join-Path $MMH "venv-gpu-diar"
$GpuPy       = Join-Path $GpuVenv "Scripts\python.exe"
$PyannoteDir = Join-Path $MMH "models\pyannote-speaker-diarization-community-1"
$TemplatesDir = Join-Path $MMH "templates"
$HfLogoutLine = "Hugging Face 的登入沒有刪除；要登出請在刪除前執行 hf auth logout，或手動刪除 %USERPROFILE%\.cache\huggingface\token"
# 〔2.0.0〕GPU 套件沒有完成的原因（與 scripts\setup_gpu_diar.py 的 REASON_TEXT 一致；tests 檢查）
$GpuReasonText = @{
    driver_too_old = "顯示卡驅動太舊（需要 570 以上）"; low_disk = "磁碟空間不足（需要 8 GB 以上）"
    no_nvidia_smi = "找不到 nvidia-smi"; pip_failed = "PyTorch 或 pyannote 安裝失敗"
    torch_cpu = "裝到的 PyTorch 不是 CUDA 版"; cuda_unavailable = "PyTorch 抓不到顯示卡"
    hf_not_logged_in = "還沒有登入 Hugging Face"; hf_not_approved = "還沒有在 Hugging Face 同意模型的使用條件"
    download_failed = "權重下載失敗"; model_incomplete = "權重檔不完整"; smoke_failed = "實測失敗"
}
function Gpu-Reason([string]$r) { if ($GpuReasonText.ContainsKey($r)) { return $GpuReasonText[$r] }; return $r }

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

# ------------------------------------------------------------------ 自動校正：設定讀取與 CLI 偵測
# 〔2.0.1〕-ErrorAction Stop：全新安裝時 config.json 還不存在，Get-Content 的非終止錯誤 try/catch 抓不到、會印紅字
function Read-Config {
    try { return Get-Content (Join-Path $MMH "config.json") -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json } catch { return $null }
}
function Get-Opt($obj, [string[]]$keys) {
    $cur = $obj
    foreach ($k in $keys) {
        if ($null -eq $cur) { return $null }
        $p = $cur.PSObject.Properties[$k]
        if (-not $p) { return $null }
        $cur = $p.Value
    }
    return $cur
}

# 依序找：設定的 cli_path → PATH → 固定位置；找到後執行 --version（不呼叫模型、不耗額度），失敗視為找不到
function Find-Cli([string]$name, $cfgPath, [string[]]$fixed) {
    $cands = @()
    if ($cfgPath) { $cands += [string]$cfgPath }
    $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $cands += $cmd.Source }
    $cands += $fixed
    foreach ($c in $cands) {
        if (-not $c -or -not (Test-Path -LiteralPath $c -PathType Leaf)) { continue }
        try {
            $out = @(& $c --version 2>$null)      # 先收完輸出再看 exit code（中途停止管線會讓 exit code 不準）
            $v = [string]($out | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and $v) { return @{ Path = $c; Version = $v.Trim() } }
        } catch { }
    }
    return $null
}

# codex login status：已登入 exit 0、未登入 exit 1（不耗額度）。只看 exit code 與第一行，不顯示、不保存其他內容
function Get-CodexAuth([string]$path) {
    $out = @()
    try { $out = @(& $path login status 2>&1) } catch { return "none" }
    if ($LASTEXITCODE -ne 0) { return "none" }
    $first = [string]($out | Select-Object -First 1)
    if ($first -match "API key") { return "api_key" }
    return "chatgpt"
}

function Model-Provider([string]$m) {
    if (-not $m) { return "" }
    if ($m -match '^(sonnet|opus|haiku)$' -or $m -match '^claude-') { return "claude" }
    if ($m -match '^gpt-' -or $m -match '^o\d') { return "openai" }
    return "?"
}

# 〔2.4.0〕畫面的供應商名稱統一為 GPT／Claude
function Provider-Label([string]$p) {
    if ($p -eq "claude") { return "Claude" }
    if ($p -eq "openai") { return "GPT" }
    return "自動選擇"
}
function Provider-Vendor([string]$p) {
    if ($p -eq "claude") { return "Claude（Anthropic）" }
    if ($p -eq "openai") { return "GPT（OpenAI）" }
    return "所選的 AI"
}

# provider: auto|claude|openai；channel: cli|api。回傳實際會用的供應商（claude／openai），沒有可用的回傳 ""
function Resolve-Provider([string]$provider, [string]$channel, $claudeCli, $codexCli) {
    if ($provider -eq "claude" -or $provider -eq "openai") { return $provider }
    if ($channel -eq "api") {
        # 〔1.1.0〕API 通道也是 GPT（OpenAI）優先（與 auto_correct.select_backend 相同）
        if ($env:OPENAI_API_KEY) { return "openai" }
        if ($env:ANTHROPIC_API_KEY) { return "claude" }
        return ""
    }
    # 〔1.1.0〕已登入的 codex 優先（gpt-6.1-sol 在實測較準、較便宜）；codex 沒登入時改用 claude
    if ($codexCli -and $script:codexAuth -ne "none") { return "openai" }
    if ($claudeCli) { return "claude" }
    if ($codexCli) { return "openai" }
    return ""
}

function Cli-Line($label, $cli, $auth) {
    if (-not $cli) { return ("  - 偵測：{0}未找到" -f $label) }
    $s = "  - 偵測：{0}已找到：{1}（{2}）" -f $label, $cli.Path, $cli.Version
    if ($auth) {
        $a = @{ chatgpt = "是（ChatGPT 帳號）"; api_key = "是（API 金鑰，依 API 用量計費）"; none = "否" }[$auth]
        $s += "，登入：$a"
    }
    return $s
}

# ------------------------------------------------------------------ uninstall
# 〔2.3.0〕會議記錄校稿（Pro 的附屬工具，另外安裝在 $MMH\proofread）：Pro 解除安裝時，它的移除程式存在就先以安靜模式
# 執行（-Quiet：不詢問、保留最近的稿清單；測試模式另傳 -TestRoot），再處理 Pro 自己的檔案與 runtime（規格 2.3.0 §4）。
# 避免留下指向不存在檔案的右鍵捷徑與 .mmproof 關聯。沒裝校稿時什麼都不做；移除程式失敗只提示，不中止 Pro 的解除安裝。
function Uninstall-Proofread {
    $u = Join-Path $MMH "proofread\uninstall.ps1"
    if (-not (Test-Path -LiteralPath $u)) { return }
    Write-Host "    先移除會議記錄校稿（Pro 的附屬工具）..."
    $ps = (Get-Process -Id $PID).Path
    $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $u, "-Quiet")
    if ($IsTest) { $a += @("-TestRoot", $TestRoot) }
    & $ps @a
    if ($LASTEXITCODE -eq 0) { Ok "已移除會議記錄校稿" }
    else { Warn "會議記錄校稿的移除程式回報錯誤（exit $LASTEXITCODE）；之後可手動執行 $u" }
}

function Do-Uninstall {
    Step "解除安裝 meeting-minutes-pro"
    Uninstall-Proofread
    if (Test-Path $SkillDst)  { Remove-Item $SkillDst -Recurse -Force; Ok "已移除 Claude CLI skill：$SkillDst" }
    if (Test-Path $SendToLnk) { Remove-Item $SendToLnk -Force; Ok "已移除右鍵「傳送到 → 會議轉寫（Pro）」" }
    if (Test-Path $SendToLnkLocal) { Remove-Item $SendToLnkLocal -Force; Ok "已移除右鍵「傳送到 → 會議轉寫（Pro，本機限定）」" }
    if (Test-Path $LegacyLnk) { Remove-Item $LegacyLnk -Force; Ok "已移除舊名稱的右鍵捷徑" }
    if (Test-Path $UploadZip) { Remove-Item $UploadZip -Force; Ok "已移除桌面上的上傳用 zip" }
    if (Test-Path $MMH) {
        $hasGpu = Test-Path $GpuVenv
        $tplFiles = @(Get-ChildItem -LiteralPath $TemplatesDir -Filter "*.md" -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "README.md" })
        Write-Host "    runtime（$MMH）裡有：venv、模型（含 1.1.0 的標點模型）、腳本、glossary.txt、corrections.tsv、"
        Write-Host "    opencc_keep.tsv、自動校正的建議歷史與對照表備份、config.json、THIRD-PARTY-NOTICES.md"
        Write-Host ("    〔2.0〕自訂範本（templates，{0} 份）、記住上次類型的 state.json{1}" -f $tplFiles.Count, $(if ($hasGpu) { "、GPU 說話者分離套件與權重（venv-gpu-diar，約 5GB）" } else { "" }))
        if ($hasGpu) { Write-Host "    要登出 Hugging Face：刪除前先執行 `"$(Join-Path $GpuVenv 'Scripts\hf.exe')`" auth logout（不登出也不影響其他程式）" }
        $size = "約 2GB"; if ($hasGpu) { $size = "約 7GB，含 GPU 說話者分離套件" }
        $ans = Read-Host "    是否一併刪除 runtime 與模型（$size）？[y/N]"
        if ($ans -match '^[yY]') {
            # 〔2.0.0 規格 §8.9〕自訂範本是使用者寫的檔案：先問，預設保留並移到桌面
            if ($tplFiles.Count -gt 0) {
                $a2 = Read-Host ("    刪除自訂範本 {0} 份？[y/N]" -f $tplFiles.Count)
                if ($a2 -notmatch '^[yY]') {
                    $bk = Join-Path $DesktopDir "meeting-minutes-pro-templates-備份"
                    if (Test-Path -LiteralPath $bk) { $bk += "-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
                    New-Item -ItemType Directory -Force -Path $bk | Out-Null
                    $tplFiles | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $bk -Force }
                    Ok ("自訂範本 {0} 份已移到 {1}" -f $tplFiles.Count, $bk)
                }
            }
            Remove-Item $MMH -Recurse -Force; Ok "已刪除 $MMH"
        } else {
            Warn "保留 $MMH（含 glossary.txt、corrections.tsv、opencc_keep.tsv 與模型，以及自訂範本與 GPU 說話者分離套件）"
        }
    }
    Write-Host "    不會變更 Claude Code、Codex 本身與它們的登入；各會議的輸出資料夾（<檔名>_minutes）也不會刪除。"
    Write-Host "    $HfLogoutLine"
    Warn "若曾上傳到 Claude App，請到 App 的「自訂 (Customize) → Skills」手動刪除 meeting-minutes-pro。"
    exit 0
}

if ($Uninstall) { Do-Uninstall }

# ------------------------------------------------------------------ 〔2.0.0〕GPU 說話者分離：移除（-RemoveGpuDiar，規格 §8.5）
function Do-RemoveGpuDiar {
    Step "移除 GPU 說話者分離套件（pyannote）"
    foreach ($d in @($GpuVenv, $PyannoteDir)) {
        if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force; Ok "已刪除 $d" }
    }
    $setup = Join-Path $MMH "scripts\setup_gpu_diar.py"
    if ((Test-Path $VenvPy) -and (Test-Path $setup)) {
        & $VenvPy -B $setup --set-status none | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "config.json：diarization.pyannote.status = none（說話者分離改用 CPU）" }
        elseif ($LASTEXITCODE -eq 5) { Warn "config.json 讀不了，沒有更新（原檔沒有被改動；見上面的原因）；轉寫時找不到 GPU 套件會自動改用 CPU" }   # 〔2.4.1〕
        else { Warn "更新 config.json 失敗；轉寫時找不到 GPU 套件會自動改用 CPU" }
    }
    Write-Host "    $HfLogoutLine"
    exit 0
}
if ($RemoveGpuDiar) { Do-RemoveGpuDiar }

# 偵測 NVIDIA 顯示卡的名稱、記憶體、驅動版本（nvidia-smi）；找不到或讀不懂回傳 $null
# MMP_TEST_NVIDIA_SMI：僅供開發測試（只在 -TestRoot 時有效）：指定假的 nvidia-smi，none＝當作不存在
function Get-NvidiaInfo {
    $exe = $null
    if ($IsTest -and $env:MMP_TEST_NVIDIA_SMI) {
        if ($env:MMP_TEST_NVIDIA_SMI -ne "none" -and (Test-Path -LiteralPath $env:MMP_TEST_NVIDIA_SMI)) { $exe = $env:MMP_TEST_NVIDIA_SMI }
    } else {
        $c = Get-Command nvidia-smi -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) { $exe = $c.Source }
    }
    if (-not $exe) { return $null }
    try { $lines = @(& $exe --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null) } catch { return $null }
    if ($LASTEXITCODE -ne 0 -or $lines.Count -eq 0) { return $null }
    $f = ([string]$lines[0]).Split(",") | ForEach-Object { $_.Trim() }
    if ($f.Count -lt 3 -or $f[1] -notmatch '^\d+$' -or $f[2] -notmatch '^(\d+)') { return $null }
    return @{ Name = $f[0]; MemMiB = [int]$f[1]; Driver = $f[2]; Major = [int]($f[2].Split(".")[0]) }
}
# 安裝位置那顆磁碟的剩餘空間（GB）；MMP_TEST_FREE_GB：僅供開發測試（只在 -TestRoot 時有效）
function Get-FreeGB {
    if ($IsTest -and $env:MMP_TEST_FREE_GB) { return [double]$env:MMP_TEST_FREE_GB }
    try { return [math]::Round(([IO.DriveInfo]::new([IO.Path]::GetPathRoot($MMH))).AvailableFreeSpace / 1GB, 0) } catch { return $null }
}
# 在 GPU venv 執行 scripts\setup_gpu_diar.py；說明與提問寫在 stderr（直接顯示），stdout 最後一行 JSON 的 gpu_diar 物件
function Invoke-GpuSetup([string[]]$a) {
    $o = @(& $GpuPy -B (Join-Path $MMH "scripts\setup_gpu_diar.py") @a)
    try { return (($o | Select-Object -Last 1) | ConvertFrom-Json).gpu_diar } catch { return $null }
}
# 規格 §8.2 步驟 1～6（步驟 7 實測在「硬體偵測、下載模型」之後，因為要用那一步下載的範例音檔）
function Install-GpuDiar {
    Step "安裝 GPU 說話者分離套件（PyTorch CUDA 版＋pyannote，約 5 GB；依網路速度約需 5～20 分鐘）"
    $ck = $null
    if (Test-Path $GpuPy) {
        $ck = Invoke-GpuSetup @("--check-torch")
        if ($ck -and $ck.status -eq "ok") { Ok "已安裝 PyTorch $($ck.torch)（CUDA 可用），略過重新安裝" }
    }
    if (-not $ck -or $ck.status -ne "ok") {
        if (-not (Test-Path $GpuPy)) {
            & $pyExe @pyPre -m venv $GpuVenv
            if ($LASTEXITCODE -ne 0) { Warn "建立 GPU 說話者分離的 venv 失敗"; return @{ status = "incomplete"; reason = "pip_failed" } }
        }
        # 先鎖 torch（2.0.0 實作時踩過：pip install pyannote.audio 會把 torch 換成 CPU 版）：版本取自 constraints-gpu-diar.txt
        $cons = Join-Path $MMH "constraints-gpu-diar.txt"
        $torchSpecs = @(Get-Content $cons -Encoding UTF8 | ForEach-Object { ($_ -replace '#.*$', '').Trim() } | Where-Object { $_ })
        $idx = "https://download.pytorch.org/whl/cu128"
        & $GpuPy -m pip install --disable-pip-version-check @torchSpecs --index-url $idx
        if ($LASTEXITCODE -ne 0) { Warn "PyTorch（CUDA 版）安裝失敗，詳見 $MMH\install.log"; return @{ status = "incomplete"; reason = "pip_failed" } }
        & $GpuPy -m pip install --disable-pip-version-check -r (Join-Path $MMH "requirements-gpu-diar.txt") -c $cons --extra-index-url $idx
        if ($LASTEXITCODE -ne 0) { Warn "pyannote 安裝失敗，詳見 $MMH\install.log"; return @{ status = "incomplete"; reason = "pip_failed" } }
        $ck = Invoke-GpuSetup @("--check-torch")
        if (-not $ck -or $ck.status -ne "ok") {
            $r = "pip_failed"; if ($ck -and $ck.reason) { $r = [string]$ck.reason }
            Warn ("GPU 說話者分離未完成：{0}" -f (Gpu-Reason $r)); return @{ status = "incomplete"; reason = $r }
        }
        Ok ("PyTorch {0}（CUDA 可用：{1}）" -f $ck.torch, $ck.gpu_name)
    }
    $pr = Invoke-GpuSetup @("--prepare")      # Hugging Face 引導（會在這個視窗提問）與下載權重
    if (-not $pr -or $pr.status -ne "ok") {
        $r = "download_failed"; if ($pr -and $pr.reason) { $r = [string]$pr.reason }
        return @{ status = "incomplete"; reason = $r }
    }
    return @{ status = "pending_smoke"; reason = $null }
}

# ------------------------------------------------------------------ 參數檢查
if ($Correct -and $NoCorrect) { Fail "-Correct 與 -NoCorrect 只能擇一" }
if ($GpuDiar -and $NoGpuDiar) { Fail "-GpuDiar 與 -NoGpuDiar 只能擇一" }
$modelProv = Model-Provider $CorrectModel
if ($modelProv -eq "?") { Fail "無法判斷 -CorrectModel $CorrectModel 屬於哪一家，請加 -CorrectProvider claude 或 openai" }
if ($modelProv -and $CorrectProvider -in @("claude", "openai") -and $modelProv -ne $CorrectProvider) {
    Fail "-CorrectModel $CorrectModel 不是 $CorrectProvider 的模型"
}
if ($modelProv -and $CorrectProvider -in @("", "auto")) { $CorrectProvider = $modelProv }

# ------------------------------------------------------------------ 〔2.4.1〕config.json 讀不了就停下（規格 2.4.1 §3）
# 存在但讀不了（權限、被鎖、不是 UTF-8、不是合法 JSON、空檔、最外層不是物件）：一開始就停下（exit 1），什麼都不寫，
# 原檔逐位元不變。檢查交給 payload 的 scripts\common.py check-config（只用標準函式庫）：已安裝的 venv 能用就用它，
# 否則用系統的 Python 3.10～3.13；兩者都沒有時改用 Test-ConfigFilePs 做同樣的檢查。
# privacy.local_only 的值看不懂（例 "true"、1、null）不算讀不了：安裝照常、值原樣保留，轉寫時當成本機限定。
function Test-ConfigFilePs([string]$f) {
    if (Test-Path -LiteralPath $f -PathType Container) { return "是資料夾，不是檔案" }
    try { $bytes = [IO.File]::ReadAllBytes($f) } catch { return ("讀取失敗（{0}）" -f $_.Exception.Message) }
    try { $txt = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($bytes) } catch { return "不是 UTF-8 編碼" }
    if ($txt.Length -eq 0 -or $txt -match '^[\s]*$') { return "是空檔" }
    if ($txt[0] -eq [char]0xFEFF) { return "不是合法的 JSON（開頭有 BOM，請存成不含 BOM 的 UTF-8）" }
    if ($txt.TrimStart()[0] -ne [char]'{') { return "最外層不是 JSON 物件" }   # PowerShell 7 的 ConvertFrom-Json 會把一個元素的陣列攤開
    try { $o = ConvertFrom-Json -InputObject $txt -ErrorAction Stop } catch { return "不是合法的 JSON" }
    if ($o -isnot [System.Management.Automation.PSCustomObject]) { return "最外層不是 JSON 物件" }
    return $null
}
function Assert-ConfigReadable {
    $cfgFile = Join-Path $MMH "config.json"
    if (-not (Test-Path -LiteralPath $cfgFile)) { return }
    $common = Join-Path $Payload "runtime\scripts\common.py"
    $exe = $null; $pre = @()
    if ((Test-Path $VenvPy) -and (Test-PyVersion $VenvPy @())) { $exe = $VenvPy }
    else { $p = Find-Python; if ($p) { $exe = $p.Exe; $pre = $p.Pre } }
    if ($exe -and (Test-Path $common)) {
        $out = @(& $exe @pre -B $common check-config 2>&1)
        $code = $LASTEXITCODE
        if ($code -eq 0) { return }
        $msg = (@($out | ForEach-Object { [string]$_ } | Where-Object { $_ -and $_ -notmatch '^\{' }) -join "`n")
        if ($code -eq 5) { Fail $msg }
        Fail ("無法檢查 {0}（exit {1}）。為了不覆寫設定，這次沒有安裝任何東西。{2}" -f $cfgFile, $code, $msg)
    }
    $why = Test-ConfigFilePs $cfgFile
    if ($why) {
        Fail ("config.json 讀不了：{0}：{1}`n為了不覆寫你的設定（包括本機限定 privacy.local_only），這次沒有寫入任何東西，檔案沒有被改動。`n請修好這個檔（UTF-8 的 JSON 物件），或刪掉它，然後重新執行。刪掉的話，重新執行安裝程式會建立新的 config.json（本機限定是關，硬體重新偵測）。" -f $why, $cfgFile)
    }
}

# ------------------------------------------------------------------ menu
if (-not (Test-Path $Payload)) { Fail "找不到 payload 資料夾，請先把整個 zip 解壓縮再執行 install.cmd" }
Assert-ConfigReadable      # 〔2.4.1〕在選單與任何寫入之前
$hasCli = Detect-ClaudeCli
$hasApp = Detect-ClaudeApp
if (-not $Target) {
    Write-Host ""
    Write-Host "  meeting-minutes-pro $Version 會議記錄 skill 安裝程式" -ForegroundColor White
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
if (-not $Breeze -and -not $NoBreeze) {
    Write-Host ""
    Write-Host "  Breeze-ASR-25（MediaTek，台灣華語／中英夾雜特化，Apache-2.0）"
    Write-Host "  - 適合中英夾雜很重的技術會議；比 turbo 準，但慢數倍"
    Write-Host "  - 額外約 1.6~3GB；Intel／CPU 電腦需在安裝時轉換模型，多花約 10~20 分鐘"
    $ans = Read-Host "  是否安裝 Breeze-ASR-25？[Y/n]"
    $Breeze = -not ($ans -match '^[nN]')
}
if ($NoBreeze) { $Breeze = $false }
$doCli = $Target -in @("CLI", "Both")
$doApp = $Target -in @("App", "Both")

# ------------------------------------------------------------------ 自動校正（選用）：偵測與詢問（只問一次）
$cfg0 = Read-Config
$hasCorrectionKey = [bool]($cfg0 -and $cfg0.PSObject.Properties["correction"])
$claudeCli = Find-Cli "claude" (Get-Opt $cfg0 @("correction", "claude", "cli_path")) @(
    (Join-Path $env:USERPROFILE ".local\bin\claude.exe"), (Join-Path $env:APPDATA "npm\claude.cmd"))
$codexCli = Find-Cli "codex" (Get-Opt $cfg0 @("correction", "openai", "cli_path")) @(
    (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe"), (Join-Path $env:APPDATA "npm\codex.cmd"))
$codexAuth = $null
if ($codexCli) { $codexAuth = Get-CodexAuth $codexCli.Path }

$corrChoice = @{}          # 要寫進 config.json 的 correction 鍵（空 = 不改）
if ($CorrectProvider) { $corrChoice.provider = $CorrectProvider }
if ($CorrectChannel)  { $corrChoice.channel = $CorrectChannel }
if ($CorrectModel)    { $corrChoice[$CorrectProvider] = @{ model = $CorrectModel } }
if ($Correct)   { $corrChoice.enabled = $true }
if ($NoCorrect) { $corrChoice.enabled = $false }

$askProvider = $CorrectProvider; if (-not $askProvider) { $askProvider = "auto" }
$askChannel  = $CorrectChannel;  if (-not $askChannel)  { $askChannel = "cli" }
if ($Correct -and -not $CorrectProvider) {
    # 不詢問直接開啟：寫入實際會用的供應商，之後不會因為新裝了另一家的 CLI 就改送到另一家
    $p = Resolve-Provider "auto" $askChannel $claudeCli $codexCli
    if ($p) { $corrChoice.provider = $p }
}
if (-not $Correct -and -not $NoCorrect -and -not $hasCorrectionKey) {
    $plan = Resolve-Provider $askProvider $askChannel $claudeCli $codexCli
    Write-Host ""
    Write-Host "  自動校正（選用）"
    Write-Host "  - 轉寫完成後，用你的 ChatGPT 或 Claude 訂閱（Codex 的 codex 指令，或 Claude Code 的 claude 指令）"
    Write-Host "    自動修正同音錯字與專有名詞，產出 transcript.corrected.md；transcript.md 原稿不會被修改"
    Write-Host (Cli-Line "claude CLI " $claudeCli $null)
    Write-Host (Cli-Line "codex CLI  " $codexCli $codexAuth)
    $askModel = $null; if ($CorrectModel -and (Model-Provider $CorrectModel) -eq $plan) { $askModel = $CorrectModel }
    if ($plan -eq "claude") {
        if (-not $askModel) { $askModel = "opus" }   # 與 common.DEFAULTS 一致
        Write-Host "  - 將使用：Claude（$askModel）。開啟後，逐字稿文字與影片截圖會送到 Claude（Anthropic）（音檔不會；要關掉截圖：config 的 reference.frames 改成 false）"
        Write-Host "    一小時會議約多花 5 分鐘，並用掉 Claude 訂閱額度；每次轉寫時可以改選模型"
        if ($codexCli -and $codexAuth -eq "none") { Write-Host "    （codex 已安裝但尚未登入，所以使用 Claude；要用 GPT 請先執行 codex login 再重新安裝並加 -Correct -CorrectProvider openai）" }
    } elseif ($plan -eq "openai") {
        if (-not $askModel) { $askModel = "gpt-6.1-sol" }
        Write-Host "  - 將使用：GPT（$askModel，透過 Codex）。開啟後，逐字稿文字與影片截圖會送到 GPT（OpenAI）（音檔不會；要關掉截圖：config 的 reference.frames 改成 false）"
        Write-Host "    一小時會議約多花 7 分鐘，並用掉 ChatGPT 訂閱的 Codex 額度；每次轉寫時可以改選模型"
        if ($codexAuth -eq "none") { Write-Host "    Codex 尚未登入：開啟後請在終端機執行 codex login 登入" }
        if ($codexAuth -eq "api_key") { Write-Host "    Codex 目前以 API 金鑰登入，會依 API 用量計費" }
    } else {
        Write-Host "  - 沒有找到 claude 或 codex 指令；回答 y 之後可以改用 API 金鑰（依用量付費）"
    }
    Write-Host "  - 這一題只決定在 Claude CLI 對話中轉寫（或直接執行 transcribe.py）時要不要自動校正；"
    Write-Host "    右鍵「傳送到」每次轉寫完都會問要不要做 AI 校正與會議摘要（1.2.0），不受這一題影響"
    $ans = Read-Host "  是否開啟自動校正？[y/N]"
    if ($ans -match '^[yY]') {
        if ($plan) {
            $corrChoice.enabled = $true; $corrChoice.provider = $plan; $corrChoice.channel = $askChannel
        } else {
            Write-Host "  沒有找到 claude 或 codex CLI。改用 API 金鑰（需自行設定環境變數，依用量付費）？"
            Write-Host "  [1] Claude（Anthropic API 金鑰，環境變數 ANTHROPIC_API_KEY）"
            Write-Host "  [2] GPT（OpenAI API 金鑰，環境變數 OPENAI_API_KEY）"
            $ans2 = Read-Host "  請選擇 [1/2/N]"
            if ($ans2 -match '^1$')     { $corrChoice.enabled = $true; $corrChoice.provider = "claude"; $corrChoice.channel = "api" }
            elseif ($ans2 -match '^2$') { $corrChoice.enabled = $true; $corrChoice.provider = "openai"; $corrChoice.channel = "api" }
            else {
                $corrChoice.enabled = $false
                Warn "未開啟。安裝 Claude Code 或 Codex 並登入後，重新執行 install.cmd -Correct 即可開啟"
            }
        }
    } else {
        $corrChoice.enabled = $false
    }
}
# 要裝哪個 API SDK：只在選了 API 通道時裝，依供應商裝 anthropic 或 openai
$apiPkgs = @()
$finalChannel = $corrChoice.channel; if (-not $finalChannel) { $finalChannel = Get-Opt $cfg0 @("correction", "channel") }
if ($finalChannel -eq "api") {
    $p = $corrChoice.provider; if (-not $p) { $p = Get-Opt $cfg0 @("correction", "provider") }
    if ($p -eq "claude") { $apiPkgs = @("anthropic") }
    elseif ($p -eq "openai") { $apiPkgs = @("openai") }
    else { $apiPkgs = @("anthropic", "openai") }
}

New-Item -ItemType Directory -Force -Path $MMH | Out-Null
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
# 清掉舊版殘留腳本：只刪 scripts\。〔2.3.0〕$MMH 底下的其他資料夾（含會議記錄校稿的 proofread\、使用者的 templates\、
# 模型、venv）一律保留：不要改成清空 $MMH（tests\test_v230.py 檢查）
if (Test-Path $scriptsDst) { Remove-Item $scriptsDst -Recurse -Force }
Copy-Item (Join-Path $Payload "runtime\scripts") $MMH -Recurse -Force
Copy-Item (Join-Path $Payload "runtime\mm-sendto.ps1") $MMH -Force
Copy-Item (Join-Path $Payload "runtime\requirements.txt") $MMH -Force
Copy-Item (Join-Path $Payload "runtime\requirements-cuda.txt") $MMH -Force
$reqApiSrc = Join-Path $Payload "runtime\requirements-api.txt"
if (Test-Path $reqApiSrc) { Copy-Item $reqApiSrc $MMH -Force }
foreach ($n in @("requirements-gpu-diar.txt", "constraints-gpu-diar.txt")) { Copy-Item (Join-Path $Payload "runtime\$n") $MMH -Force }   # 〔2.0.0〕
Copy-Item (Join-Path $Here "README.md") $MMH -Force
$notices = Join-Path $Here "THIRD-PARTY-NOTICES.md"
if (Test-Path $notices) { Copy-Item $notices $MMH -Force }
$gloss = Join-Path $MMH "glossary.txt"
if (-not (Test-Path $gloss)) { Copy-Item (Join-Path $Payload "runtime\glossary.txt") $gloss; Ok "已建立 glossary.txt（可自行編輯專有名詞）" }
else { Ok "保留既有的 glossary.txt" }
$corr = Join-Path $MMH "corrections.tsv"
if (-not (Test-Path $corr)) { Copy-Item (Join-Path $Payload "runtime\corrections.tsv") $corr; Ok "已建立 corrections.tsv（固定錯誤對照表）" }
else { Ok "保留既有的 corrections.tsv" }
# 〔2.0.0 規格 §3.8.1、§9.2〕自訂範本目錄：已存在就不動使用者的範本，只更新 README.md
New-Item -ItemType Directory -Force -Path $TemplatesDir | Out-Null
Copy-Item (Join-Path $Payload "runtime\templates\README.md") (Join-Path $TemplatesDir "README.md") -Force
$tplCount = @(Get-ChildItem -LiteralPath $TemplatesDir -Filter "*.md" -File | Where-Object { $_.Name -ne "README.md" }).Count
if ($tplCount -gt 0) { Ok "保留既有的自訂範本 $tplCount 份（$TemplatesDir）" } else { Ok "已建立自訂範本目錄（$TemplatesDir，格式說明見 README.md）" }

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

# ------------------------------------------------------------------ 〔2.0.0〕GPU 說話者分離（選用；規格 §8.1～§8.5）
# 結果寫進 config.json 的 diarization.pyannote（status／reason；在「更新設定」那一步寫，$GpuResult 為 $null 時不改）
$GpuResult = $null
$gpuStatus0 = [string](Get-Opt $cfg0 @("diarization", "pyannote", "status"))
$gpuReason0 = [string](Get-Opt $cfg0 @("diarization", "pyannote", "reason"))
if ($NoGpuDiar) {
    $GpuResult = @{ status = "none"; reason = $null }
    Ok "GPU 說話者分離：不安裝（-NoGpuDiar）；說話者分離用 CPU"
} elseif (-not $hasNvidia) {
    if ($GpuDiar) { Warn "沒有偵測到 NVIDIA 顯示卡：GPU 說話者分離無法安裝，說話者分離用 CPU" }
    if (-not $gpuStatus0 -or $gpuStatus0 -eq "none") { $GpuResult = @{ status = "none"; reason = $null } }
} elseif ($gpuStatus0 -eq "ready" -and -not $GpuDiar) {
    Ok "GPU 說話者分離：已安裝（要移除：install.cmd -RemoveGpuDiar）"
} elseif ($gpuStatus0 -eq "incomplete" -and -not $GpuDiar) {
    Warn ("GPU 說話者分離套件未完成（{0}），要補完成請執行 install.cmd -GpuDiar" -f (Gpu-Reason $gpuReason0))
} else {
    $nv = Get-NvidiaInfo
    $freeGB = Get-FreeGB
    if (-not $nv) {
        Warn "找不到 nvidia-smi（NVIDIA 驅動程式附的工具），略過 GPU 說話者分離；更新或重新安裝顯示卡驅動後執行 install.cmd -GpuDiar"
        $GpuResult = @{ status = "none"; reason = "no_nvidia_smi" }
    } elseif ($nv.Major -lt 570) {
        Warn ("顯示卡驅動 {0} 太舊，GPU 說話者分離需要 570 以上；更新驅動後執行 install.cmd -GpuDiar" -f $nv.Driver)
        $GpuResult = @{ status = "none"; reason = "driver_too_old" }
    } elseif ($null -ne $freeGB -and $freeGB -lt 8) {
        Warn ("磁碟只剩 {0} GB，GPU 說話者分離需要約 8 GB；清出空間後執行 install.cmd -GpuDiar" -f $freeGB)
        $GpuResult = @{ status = "none"; reason = "low_disk" }
    } else {
        $go = [bool]$GpuDiar
        if (-not $go) {
            Write-Host ""
            Write-Host "  GPU 說話者分離（選用）"
            Write-Host ("  - 偵測：{0}（{1} GB，驅動 {2}）" -f $nv.Name, [math]::Round($nv.MemMiB / 1024), $nv.Driver)
            Write-Host "  - 用 pyannote（speaker-diarization-community-1）在顯示卡上做說話者分離："
            Write-Host "    每小時錄音約 1.5 分鐘（目前的 CPU 方式約 3.5 分鐘）"
            Write-Host "  - 準確度：合成測試素材上兩種方式互有勝負（會議、課程、訪談 GPU 較準；座談會把發言很少的觀眾併掉），"
            Write-Host "    所以「座談」類型預設仍用 CPU；其他類型有 GPU 時自動用 GPU"
            Write-Host ("  - 需要下載約 5 GB（PyTorch CUDA 版＋pyannote），裝在 {0}；磁碟剩 {1} GB" -f $GpuVenv, $freeGB)
            Write-Host "  - 模型要你自己到 Hugging Face（放 AI 模型的網站）登入並同意使用條件，免費；下一步會一步一步引導；授權 CC-BY-4.0"
            Write-Host "  - 不裝也能正常使用：說話者分離照舊用 CPU；之後想裝再執行 install.cmd -GpuDiar"
            $ans = Read-Host "  是否安裝 GPU 說話者分離？[y/N]"
            $go = $ans -match '^[yY]'
        }
        if ($go) { $GpuResult = Install-GpuDiar }
        else { $GpuResult = @{ status = "none"; reason = $null }; Ok "不安裝 GPU 說話者分離（之後想裝：install.cmd -GpuDiar）" }
    }
}

if ($apiPkgs.Count -gt 0) {
    Step ("安裝自動校正 API 通道套件：" + ($apiPkgs -join "、"))
    $specs = @()
    $reqApi = Join-Path $MMH "requirements-api.txt"
    $lines = @(); if (Test-Path $reqApi) { $lines = @(Get-Content $reqApi -Encoding UTF8) }
    foreach ($pkg in $apiPkgs) {
        $line = $lines | Where-Object { $_ -match "^\s*$pkg(\s*[<>=!~\[;]|\s*$)" } | Select-Object -First 1
        if ($line) { $specs += ($line -replace '\s+#.*$', '').Trim() } else { $specs += $pkg }
    }
    & $VenvPy -m pip install -U @specs --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) { Ok ("已安裝 " + ($specs -join "、")) }
    else { Warn "API 套件安裝失敗；之後可執行 `"$VenvPy`" -m pip install -r `"$reqApi`"" }
}

Step "硬體偵測、下載模型與實測（只在安裝時進行一次）"
$sbArgs = @((Join-Path $MMH "scripts\setup_backend.py"), "--whisper", $Whisper)
if ($Backend) { $sbArgs += @("--force", $Backend) }
# 〔1.2.1〕-ComputeType 明確指定精度；不指定時 setup_backend.py 在後端與裝置相同時沿用 config.json 既有的 compute_type
if ($ComputeType) {
    if ($Backend) { $sbArgs += @("--compute-type", $ComputeType) }
    else { Warn "-ComputeType 要搭配 -Backend 使用（自動偵測時精度由實測決定），這次忽略" }
}
if ($KeepAll) { $sbArgs += "--keep-all" }
if ($Breeze)  { $sbArgs += "--breeze" }
$sbOut = @()
# 〔1.2.2〕MMP_INSTALLING=1：config.json 的 runtime_version 要到「更新設定」才更新，這裡的版號提示改印「升級中」而不是「請重新執行安裝程式」
$env:MMP_INSTALLING = "1"
& $VenvPy @sbArgs | Tee-Object -Variable sbOut
$sbCode = $LASTEXITCODE
Remove-Item Env:MMP_INSTALLING -ErrorAction SilentlyContinue
if ($sbCode -ne 0) { Fail "硬體偵測或模型下載失敗（需可連線 huggingface.co 與 github.com），詳見 $MMH\install.log" }
$choice = $null
try { $choice = ($sbOut | Select-Object -Last 1) | ConvertFrom-Json } catch { }
if ($choice -and $choice.prune_ct2_packages -and $cudaInstalled) {
    Write-Host "    CUDA 後端未被選用，移除其套件以節省空間 ..."
    & $VenvPy -m pip uninstall -y faster-whisper ctranslate2 nvidia-cublas-cu12 nvidia-cudnn-cu12 --disable-pip-version-check | Out-Null
}
$punctOk = [bool]($choice -and $choice.punct)
# 〔2.0.0 規格 §8.4〕GPU 說話者分離實測：用上一步下載的範例音檔跑一次（離線、關閉 pyannote 使用統計）
if ($GpuResult -and $GpuResult.status -eq "pending_smoke") {
    Step "GPU 說話者分離實測"
    $sm = Invoke-GpuSetup @("--smoke")
    if ($sm -and $sm.status -eq "ready") { $GpuResult = @{ status = "ready"; reason = $null; gpu = $sm.gpu_name; sec = $sm.smoke_sec } }
    else { $GpuResult = @{ status = "incomplete"; reason = "smoke_failed" } }
}
if (-not $punctOk) {
    Warn "標點模型未安裝：逐字稿仍會分段，turbo 沿用 Whisper 標點。之後可執行 `"$VenvPy`" `"$MMH\scripts\setup_backend.py`" --punct-only 補裝"
}

Step "更新設定（config.json）與 OpenCC 詞彙回復表"
# 補上 1.1.0／1.2.0 新增的設定鍵（已存在的鍵與使用者改過的值一律保留）；建立使用者的 opencc_keep.tsv（不存在才建立）
$env:MMP_SCRIPTS = $scriptsDst
$env:MMP_CORRECTION = ($corrChoice | ConvertTo-Json -Compress -Depth 5)
if ($GpuResult) { $env:MMP_GPU_DIAR = (@{ status = $GpuResult.status; reason = $GpuResult.reason } | ConvertTo-Json -Compress) }
$upgradePy = @'
import copy, json, os, sys
sys.path.insert(0, os.environ['MMP_SCRIPTS'])
import common
import opencc_keep

def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v

choice = json.loads(os.environ.get('MMP_CORRECTION') or '{}') or {}
before = common.load_config()
cfg = common.upgrade_config()
added = common.added_config_keys(before, cfg)   # 〔1.2.2〕實際補上的鍵（不含安裝時的明確選擇與 runtime_version）
if choice:
    cur = cfg.get('correction')
    if not isinstance(cur, dict):
        cur = copy.deepcopy(common.DEFAULTS['correction'])
    merge(cur, choice)
    cfg = common.upgrade_config(correction=cur)
# 〔2.0.0 規格 §8.2 步驟 8〕GPU 說話者分離的結果（只有安裝程式寫 status；沒有結果時不改）
gd = json.loads(os.environ.get('MMP_GPU_DIAR') or 'null')
if gd:
    d = cfg.setdefault('diarization', {})
    p = d.setdefault('pyannote', {})
    p['status'] = gd.get('status')
    p['reason'] = gd.get('reason')
    common.config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
_, user = common.opencc_keep_paths()
created = False
if not user.exists():
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(opencc_keep.USER_TEMPLATE, encoding='utf-8')
    created = True
print(json.dumps({'correction': cfg.get('correction'), 'punctuation': cfg.get('punctuation'),
                  'opencc_keep': str(user), 'opencc_keep_created': created, 'added_keys': added}, ensure_ascii=False))
'@
$upOut = @($upgradePy | & $VenvPy -B -)
$upCode = $LASTEXITCODE
Remove-Item Env:MMP_CORRECTION -ErrorAction SilentlyContinue
Remove-Item Env:MMP_GPU_DIAR -ErrorAction SilentlyContinue
Remove-Item Env:MMP_SCRIPTS -ErrorAction SilentlyContinue
$up = $null
if ($upCode -eq 0) { try { $up = ($upOut | Select-Object -Last 1) | ConvertFrom-Json } catch { } }
if ($up) {
    # 〔1.2.2〕依實際情況：有補鍵時列出補了哪些，沒有補任何鍵時寫「設定鍵無變更」
    $added = @($up.added_keys | Where-Object { $_ })
    if ($added.Count -gt 0) { Ok ("config.json 已補上新版設定鍵：{0}（既有的值不變）" -f ($added -join "、")) }
    else { Ok "config.json 設定鍵無變更（runtime_version 更新為 $Version）" }
    if ($up.opencc_keep_created) { Ok "已建立 opencc_keep.tsv（OpenCC 詞彙回復表的使用者表，可自行加詞）" }
    else { Ok "保留既有的 opencc_keep.tsv" }
} elseif ($upCode -eq 5) {
    # 〔2.4.1〕安裝途中 config.json 變得讀不了（開頭已檢查過）：upgrade_config() 丟 ConfigUnreadable，沒有寫入
    Fail ("config.json 讀不了，沒有更新（原檔沒有被改動）。{0}" -f (@($upOut | Where-Object { $_ -and $_ -notmatch '^\{' }) -join " "))
} else {
    Warn "更新 config.json 失敗（exit $upCode）；轉寫仍照 $Version 預設值執行。可重新執行 install.cmd 再試一次"
}

Step "建立右鍵「傳送到 → 會議轉寫（Pro）」與「會議轉寫（Pro，本機限定）」"
if (Test-Path $LegacyLnk) { Remove-Item $LegacyLnk -Force; Ok "已移除舊名稱「會議轉寫 Pro」的捷徑（改為標示版本的名稱）" }
# 〔2.4.0〕兩個右鍵入口（規格 2.4.0 §4）：一般的、本機限定的（帶 -LocalOnly）。重複安裝時覆寫，不另建
function New-SendToLink([string]$path, [string]$extraArgs, [string]$desc) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($path)
    $lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$MMH\mm-sendto.ps1`"$extraArgs"
    $lnk.WorkingDirectory = $MMH
    $lnk.IconLocation = "$env:SystemRoot\System32\SndVol.exe,0"
    $lnk.Description = $desc
    $lnk.Save()
}
New-SendToLink $SendToLnk "" "會議轉寫（Pro）：本機轉寫會議錄音／錄影（meeting-minutes-pro）"
Ok "對錄音或錄影檔按右鍵 → 傳送到 → 會議轉寫（Pro）"
New-SendToLink $SendToLnkLocal " -LocalOnly" "會議轉寫（Pro，本機限定）：本機轉寫，這份不送 GPT 或 Claude（meeting-minutes-pro）"
Ok "機敏會議：右鍵 → 傳送到 → 會議轉寫（Pro，本機限定）（不做 AI 校正與整理，輸出資料夾會標記 local-only.json）"

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
    Copy-Item (Join-Path $Payload "skill\meeting-minutes-pro") $SkillDst -Recurse -Force
    Ok "完成。Claude CLI 或桌面版 Code 分頁新開的 session 即可使用"
}

if ($doApp) {
    Step "準備 Claude App 上傳檔"
    Copy-Item (Join-Path $Payload "meeting-minutes-pro-upload.zip") $UploadZip -Force
    Ok "已放到桌面：$UploadZip"
    Write-Host "    請在 Claude App：左側「自訂 (Customize)」→「Skills」→「+」→「Create skill」→「Upload a skill」，選擇上面的 zip。"
    Write-Host "    （需在「設定 → Capabilities」開啟程式碼執行。網頁版：https://claude.ai/customize/skills）"
    if (-not $IsTest) { Start-Process explorer.exe "/select,`"$UploadZip`"" }
}

# ------------------------------------------------------------------ summary
Step "安裝完成（meeting-minutes-pro $Version）"
$cfg = Read-Config
Write-Host "    runtime ：$MMH"
Write-Host "    選定後端：$($cfg.backend) / $($cfg.device) / $($cfg.compute_type)　模型：$($cfg.whisper)"
if ($cfg.profiles -and $cfg.profiles.breeze) {
    $b = $cfg.profiles.breeze
    Write-Host "    Breeze  ：$($b.backend) / $($b.device)（RTF $($b.rtf)）　轉寫時加 --whisper breeze"
}
Write-Host "    對照表  ：$corr"
Write-Host "    專有名詞：$gloss"
if ((Get-Opt $cfg @("punctuation", "enabled")) -eq $false) { Write-Host "    分段標點：關（config.json 的 punctuation.enabled）" }
elseif ($punctOk) { Write-Host "    分段標點：開（標點模型 OK）" }
else { Write-Host "    分段標點：開（標點模型未安裝，目前只分段；執行 setup_backend.py --punct-only 補裝）" }
Write-Host "    OpenCC 詞彙回復表：$(Join-Path $MMH 'opencc_keep.tsv')"
$c = Get-Opt $cfg @("correction")
if ($c -and $c.enabled) {
    $ch = [string]$c.channel; if (-not $ch) { $ch = "cli" }
    $p = Resolve-Provider ([string]$c.provider) $ch $claudeCli $codexCli
    $m = Get-Opt $c @($p, "model"); if (-not $m) { $m = @{ claude = "opus"; openai = "gpt-6.1-sol" }[$p] }   # 與 common.DEFAULTS 一致
    if ($ch -eq "api") {
        $key = @{ claude = "ANTHROPIC_API_KEY"; openai = "OPENAI_API_KEY" }[$p]
        if ($p) { $how = "API 通道（未實測），需環境變數 $key" } else { $how = "API 通道（未實測），需環境變數 ANTHROPIC_API_KEY 或 OPENAI_API_KEY" }
    } elseif ($p -eq "claude" -and $claudeCli) { $how = "訂閱 CLI：$($claudeCli.Path)" }
    elseif ($p -eq "openai" -and $codexCli) {
        $how = "Codex CLI：$($codexCli.Path)"
        if ($codexAuth -eq "none") { $how += "；尚未登入，請執行 codex login" }
    }
    else { $how = "找不到對應的 CLI，轉寫時會略過；安裝並登入後即可使用" }
    Write-Host ("    自動校正（CLI 對話與命令列）：開（{0} {1}，{2}）；逐字稿文字與影片截圖會送到 {3}" -f (Provider-Label $p), $m, $how, (Provider-Vendor $p))
    $ca = Get-Opt $c @("corrections_auto", "mode")
    if ($ca -and $ca -ne "off") { Write-Host "    對照表自動寫入：$ca（config.json 的 correction.corrections_auto）" }
} else {
    Write-Host "    自動校正（CLI 對話與命令列）：關（要開啟：重新執行 install.cmd -Correct）"
}
# 〔2.0.0 規格 §8.6〕說話者分離與內容類型
$pst = [string](Get-Opt $cfg @("diarization", "pyannote", "status")); $prs = [string](Get-Opt $cfg @("diarization", "pyannote", "reason"))
if ($pst -eq "ready") {
    $how = "可用"; if ($GpuResult -and $GpuResult.gpu) { $how += "，{0}，實測 {1} 秒" -f $GpuResult.gpu, $GpuResult.sec }
    Write-Host "    說話者分離：GPU（pyannote，$how）；「座談」類型預設用 CPU（sherpa）"
} elseif ($pst -eq "incomplete") {
    Write-Host ("    說話者分離：CPU（sherpa；GPU 套件未完成：{0}；照引導完成後執行 install.cmd -GpuDiar）" -f (Gpu-Reason $prs))
} elseif ($prs) {
    Write-Host ("    說話者分離：CPU（sherpa；GPU 套件未安裝：{0}）" -f (Gpu-Reason $prs))
} else {
    Write-Host "    說話者分離：CPU（sherpa；GPU 套件未安裝）"
}
Write-Host "    內容類型：預設 會議（轉寫時第一題可改選，會記住上次的選擇）；自訂範本目錄 $TemplatesDir"
Write-Host "    右鍵「傳送到」：轉寫完會問「要做 AI 校正嗎？」「要產生會議摘要嗎？」（按 Enter＝是；config.json 的 correction.ask_default、minutes.ask_default）"
# 〔2.4.0〕本機限定（規格 2.4.0 §2）；〔2.4.1〕判定交給 scripts\common.py local-only（privacy.local_only 的值看不懂也算開）
$loSum = $null
try { $loSum = (@(& $VenvPy -B (Join-Path $MMH "scripts\common.py") local-only 2>$null) | Select-Object -Last 1) | ConvertFrom-Json } catch { }
if ($loSum -and $loSum.local_only -eq $true -and $loSum.source -eq "config") {
    Write-Host "    本機限定：開（config.json 的 privacy.local_only；每一份都不送 GPT 或 Claude，右鍵轉寫不問 AI 校正與整理）"
} elseif ($loSum -and $loSum.local_only -eq $true) {
    Write-Host ("    本機限定：開（{0}；每一份都不送 GPT 或 Claude，右鍵轉寫不問 AI 校正與整理）" -f $loSum.why) -ForegroundColor Yellow
    Write-Host ("    要恢復：{0}" -f $loSum.how) -ForegroundColor Yellow
} else {
    Write-Host "    本機限定：關（機敏會議用右鍵「會議轉寫（Pro，本機限定）」；整部電腦都不送雲端：config.json 的 privacy.local_only 改成 true）"
}
Write-Host "    執行 log：每個輸出資料夾的 run_log.jsonl；歷次摘要 $(Join-Path $MMH 'logs\runs.jsonl')（彙整：scripts\runlog.py summary）"
Write-Host "    （硬體或驅動變更後，重新執行 install.cmd 即可重新偵測）"
if ($doCli) { Write-Host "    CLI 用法：在 Claude CLI 說「用 meeting-minutes-pro 整理 D:\會議\0912.mp4，與會 5 人」" }
if ($doApp) { Write-Host "    App 用法：右鍵轉寫 → 把 transcript.md（有自動校正時用 transcript.corrected.md）附到 Claude App →「整理成會議記錄」；轉寫完選了會議摘要時，另有 AI 整理的 meeting-minutes.md" }
if ($doCli -and $doApp) {
    Warn "若 Claude CLI 以 claude.ai 帳號登入，上傳到 App 的 skill 也會同步到 CLI；看到兩個 meeting-minutes-pro 時，兩者內容相同，用哪個都可以。"
}
try { Stop-Transcript | Out-Null } catch { }
