# 檔案總管右鍵「傳送到 → 會議轉寫（Pro）」的執行腳本（meeting-minutes-pro 2.4.0）
# 流程（1.2.0）：先問轉寫要用的資訊 → 轉寫 → 逐字稿完成後依序問「要做 AI 校正嗎？」「要產生會議摘要嗎？」（按 Enter＝是）
# 〔1.2.2〕每次詢問（含最後的「按 Enter 關閉」）前先清空鍵盤緩衝（Clear-KeyBuffer）
# 〔2.0.0〕轉寫前的提問：內容類型（含自訂範本；記住上次，$MMH\state.json）→ 講者人數／s 略過 → 專有名詞 → Breeze（規格 §7.1、§7.2）；
#         整理的題目與輸出依類型（會議：meeting-minutes.md；其他：notes.md）；結束畫面列字幕、說話者分離退回與零星講者（§7.4）
# 〔2.0.1〕讀檔的 cmdlet 加 -ErrorAction Stop：Get-Content／Select-String 找不到檔案是「非終止錯誤」，try/catch 抓不到，
#         會在主控台印紅字（第一次執行時 state.json 還不存在）。現在讀不到、壞掉的 JSON 都安靜地當作沒有
# 〔2.1.0〕網頁版（規格 2.1.0 §7.1）：不加題目；auto_minutes.py 會接著產生 meeting-minutes.html／notes.html。結束畫面讀
#         auto_minutes.json 的 html：產生成功才列 .html（括號依 media：found／explicit「時間碼可點播放」，其他「時間碼為文字」），
#         「下一步」改成打開 .html；網頁版失敗時多一行黃字（原因與 render_html.py 補做的指令）
# 〔2.2.0〕參考資料（規格 2.2.0 §7.1、§7.2）：詢問行依 refs.py plan 列出會送出的內容（截圖 N 張、會議文件 M 份）；
#         答應 AI 校正（或只答應摘要）後，沒有說明檔與 context.md 時問一行背景說明（每個檔各問一次；讀完再清一次鍵盤緩衝，
#         貼上多行時第二行以後不會被下一題吃掉），答案以 --context 傳給第一個答應的步驟；結束畫面列 reference.json、context.md
# 〔2.4.0〕本機限定（規格 2.4.0 §2、§3）：右鍵「傳送到 → 會議轉寫（Pro，本機限定）」以 -LocalOnly 執行本腳本；或 config.json 的
#         privacy.local_only: true；或輸出資料夾已有標記檔 local-only.json。本機限定時不偵測 claude／codex、不問 AI 校正與整理，
#         轉寫加 --local-only（寫標記檔）；結束畫面寫明「本機限定：沒有送出任何資料」並提示用會議記錄校稿人工校稿
# 〔2.4.0〕供應商名稱統一為 GPT／Claude（「會送到 GPT（OpenAI）」「[Enter] 預設（GPT gpt-6.1-sol）」）
param([switch]$LocalOnly, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
# 本腳本由安裝程式放在 runtime 根目錄；讓轉寫腳本用同一個位置（也支援 MEETING_MINUTES_PRO_HOME 改放的位置）
$MMH = $PSScriptRoot
if (-not $MMH) { $MMH = Split-Path -Parent $MyInvocation.MyCommand.Path }
$env:MEETING_MINUTES_PRO_HOME = $MMH
$Py = Join-Path $MMH "venv\Scripts\python.exe"
$Scripts = Join-Path $MMH "scripts"
$cfg = $null
try { $cfg = Get-Content (Join-Path $MMH "config.json") -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json } catch { }
# 〔1.2.0〕標題列與第一行顯示版號：取 scripts\common.py 的 VERSION，讀不到時用 config.json 的 runtime_version；不一致時兩個都印
$verCode = $null
try {
    $m = Select-String -LiteralPath (Join-Path $Scripts "common.py") -Pattern '^VERSION\s*=\s*"([^"]+)"' -Encoding UTF8 -ErrorAction Stop | Select-Object -First 1
    if ($m) { $verCode = $m.Matches[0].Groups[1].Value }
} catch { }
$verCfg = $null; if ($cfg -and $cfg.PSObject.Properties["runtime_version"]) { $verCfg = [string]$cfg.runtime_version }
if ($verCode) { $verLine = "meeting-minutes-pro $verCode" } elseif ($verCfg) { $verLine = "meeting-minutes-pro $verCfg（取自 config.json）" } else { $verLine = "meeting-minutes-pro（版號不明）" }
if ($verCode -and $verCfg -and $verCode -ne $verCfg) { $verLine += "（config.json 的 runtime_version 是 $verCfg，版號不一致：請重新執行安裝程式）" }
# 〔2.4.0〕本機限定：入口（-LocalOnly）或全域設定（config.json 的 privacy.local_only: true）
$LocalOnlyMarker = "local-only.json"   # 與 scripts\common.py 的 LOCAL_ONLY_MARKER 一致（tests 檢查）
$LoCfg = $false; try { $LoCfg = ($cfg.privacy.local_only -eq $true) } catch { }
$LoStart = $LocalOnly.IsPresent -or $LoCfg
$EntryName = "會議轉寫（Pro）"; if ($LocalOnly) { $EntryName = "會議轉寫（Pro，本機限定）"; $env:MMP_LOCAL_ONLY_SOURCE = "sendto" }
$Host.UI.RawUI.WindowTitle = "$EntryName$verLine"
Write-Host "==== $EntryName　$verLine ====" -ForegroundColor Magenta
if ($cfg) { Write-Host ("後端：{0} / {1}　模型：{2}" -f $cfg.backend, $cfg.device, $cfg.whisper) }
if ($LoStart) {
    $loWhy = @(); if ($LocalOnly) { $loWhy += "本機限定的右鍵入口" }; if ($LoCfg) { $loWhy += "config.json 的 privacy.local_only" }
    Write-Host ("本機限定（{0}）：這次不會把任何資料送到 GPT 或 Claude；轉寫與字幕都在這部電腦完成，不做 AI 校正與整理" -f ($loWhy -join "、")) -ForegroundColor Yellow
}

# 〔1.2.2〕詢問前清空主控台輸入緩衝：轉寫或 AI 處理中誤按的 Enter／按鍵會留在緩衝區，
# 被下一題或最後的「按 Enter 關閉」吃掉（視窗直接關閉、題目被誤答）。
# stdin 被導向（管線、測試）或沒有主控台（例如 ISE）時略過；任何錯誤都吞掉，不得讓入口出錯。
function Clear-KeyBuffer {
    try { if ([Console]::IsInputRedirected) { return } } catch { return }
    try { $Host.UI.RawUI.FlushInputBuffer(); return } catch { }
    try { while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) } } catch { }
}

if (-not (Test-Path $Py)) { Write-Host "尚未安裝 runtime，請重新執行 install.cmd" -ForegroundColor Red; Clear-KeyBuffer; Read-Host "按 Enter 關閉"; exit 1 }
if (-not $Files -or $Files.Count -eq 0) { Write-Host "請在檔案總管對錄音或錄影檔按右鍵 → 傳送到 → $EntryName"; Clear-KeyBuffer; Read-Host "按 Enter 關閉"; exit 1 }

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
function Now-Iso { return (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffzzz") }
# 等使用者回答：回傳 @(答案, 開始, 結束)；時間寫進執行 log（等待時間不算處理時間）
function Ask([string]$prompt) {
    Clear-KeyBuffer   # 〔1.2.2〕先清掉處理中誤按的鍵，等待時間從清完開始算
    $a = Now-Iso; $ans = Read-Host $prompt; $b = Now-Iso
    return @([string]$ans, $a, $b)
}
function Log-Wait([string]$out, [string]$name, [string]$a, [string]$b) {
    if ($out -and (Test-Path -LiteralPath $out)) { & $Py (Join-Path $Scripts "runlog.py") wait $out --name $name --start $a --end $b 2>$null | Out-Null }
}
# 只找執行檔（不呼叫模型）；實際呼叫與 --version 檢查由 Python 腳本做
function Find-Cli([string]$name, $cfgPath, [string[]]$fixed) {
    if ($cfgPath -and (Test-Path -LiteralPath ([string]$cfgPath) -PathType Leaf)) { return [string]$cfgPath }
    $c = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.Source }
    foreach ($f in $fixed) { if ($f -and (Test-Path -LiteralPath $f -PathType Leaf)) { return $f } }
    return $null
}
# codex login status（不耗額度，與 Python 腳本的判斷相同：exit 0＝已登入）；不印、不存輸出
function Test-CodexLogin([string]$exe) {
    $keep = @{}
    foreach ($k in @("OPENAI_API_KEY", "CODEX_API_KEY")) {
        $keep[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, $null, "Process")
    }
    try { & $exe login status *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
    finally { foreach ($k in @($keep.Keys)) { [Environment]::SetEnvironmentVariable($k, $keep[$k], "Process") } }
}
function Format-Duration([double]$sec) {
    $h = [math]::Floor($sec / 3600); $m = [math]::Round(($sec % 3600) / 60)
    if ($m -ge 60) { $h += 1; $m = 0 }
    if ($h -gt 0) { return "{0} 小時 {1} 分" -f $h, $m }
    if ($m -lt 1) { return "不到 1 分" }
    return "{0} 分" -f $m
}
function Get-Duration([string]$f) {
    try {
        $d = & ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>$null | Select-Object -Last 1
        if ($LASTEXITCODE -eq 0 -and $d) { return [double]::Parse(([string]$d).Trim(), [Globalization.CultureInfo]::InvariantCulture) }
    } catch { }
    return $null
}
# 每小時錄音的實測（README〈時間與費用〉）：分鐘下限、上限、API 等價美元下限、上限
# AI 校正：1.1.0 的合成素材實測；會議摘要：1.2.0 的合成素材實測（規格附錄 F）
$Rates = @{
    correction = @{
        "claude:opus"        = @(4.6, 5.2, 0.88, 1.03)
        "claude:sonnet"      = @(2.8, 4.6, 0.4, 0.55)
        "openai:gpt-6.1-sol" = @(6.7, 7.0, 0.35, 0.45)
    }
    minutes = @{
        "claude:opus"        = @(4.0, 6.4, 0.84, 1.18)
        "claude:sonnet"      = @(2.3, 2.6, 0.35, 0.37)
        "openai:gpt-6.1-sol" = @(5.7, 7.5, 0.22, 0.33)
    }
}
$RatesFallback = @{
    correction = @{ claude = @(2.8, 5.2, 0.4, 1.03); openai = @(6.7, 7.0, 0.35, 0.45) }
    minutes    = @{ claude = @(2.3, 6.4, 0.35, 1.18); openai = @(5.7, 7.5, 0.22, 0.33) }
}
function Round-Half([double]$x) { return [math]::Round($x, [MidpointRounding]::AwayFromZero) }
function Format-Span([double]$lo, [double]$hi) {
    if ($hi -lt 1) { return "不到 1 分鐘" }
    $a = [math]::Max(1, (Round-Half $lo)); $b = [math]::Max($a, (Round-Half $hi))
    if ($a -eq $b) { return "約 {0} 分鐘" -f $b }
    return "約 {0}～{1} 分鐘" -f $a, $b
}
function Format-Usd([double]$lo, [double]$hi) {
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $a = $lo.ToString("0.00", $inv); $b = $hi.ToString("0.00", $inv)
    if ($a -eq $b) { return "US`$$a" }
    return "US`$$a～$b"
}
function Format-Estimate($rate, $hours) {
    if (-not $rate) { return "沒有實測數字" }
    if ($null -eq $hours) {
        return "每小時錄音{0}、API 等價約 {1}" -f (Format-Span $rate[0] $rate[1]), (Format-Usd $rate[2] $rate[3])
    }
    $h = [double]$hours
    return "{0}、API 等價約 {1}" -f (Format-Span ($rate[0] * $h) ($rate[1] * $h)), (Format-Usd ($rate[2] * $h) ($rate[3] * $h))
}
function Get-Rate([string]$section, [string]$key) {
    $r = $Rates[$section][$key]; if ($r) { return $r }
    return $RatesFallback[$section][$key.Split(":")[0]]
}

# ------------------------------------------------------------------ 〔2.0.0〕內容類型（規格 §7.1、§7.2）
# 7 種內建類型：名稱、筆記稱呼、人數題是否把「s＝略過」寫進主句（與 scripts\content_types.py 的 TYPES 一致；tests 檢查）
$Types = @(
    @{ code = "meeting";      label = "會議（含業務／客戶會議）";   noun = "會議摘要";     skipMain = $false },
    @{ code = "course";       label = "課程（含演講／專題分享）";   noun = "課程筆記";     skipMain = $true },
    @{ code = "interview";    label = "訪談節目（Podcast、專訪）";  noun = "訪談筆記";     skipMain = $false },
    @{ code = "tutorial";     label = "操作教學／示範";             noun = "操作教學筆記"; skipMain = $true },
    @{ code = "panel";        label = "座談／論壇／研討會";         noun = "座談筆記";     skipMain = $false },
    @{ code = "workshop";     label = "腦力激盪／工作坊／回顧";     noun = "工作坊筆記";   skipMain = $false },
    @{ code = "requirements"; label = "客戶／需求訪談";             noun = "需求訪談筆記"; skipMain = $false })
function Short-Label([string]$label) { return $label.Split("（")[0] }
function Type-Of([string]$code) { return $Types | Where-Object { $_.code -eq $code } | Select-Object -First 1 }
# 顯示寬度（中日韓全形字算 2 格），選單對齊用
function Disp-Width([string]$s) { $w = 0; foreach ($ch in $s.ToCharArray()) { if ([int]$ch -ge 0x2E80) { $w += 2 } else { $w += 1 } }; return $w }
function Pad-Disp([string]$s, [int]$w) { return $s + (" " * [math]::Max(1, $w - (Disp-Width $s))) }
$StatePath = Join-Path $MMH "state.json"
# 〔2.0.1〕第一次執行時 state.json 不存在：先 Test-Path，不印任何錯誤；讀取失敗、壞掉的 JSON 也安靜地當作沒有記錄
function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json } catch { return $null }
}
# 記住上次的類型：寫入失敗只略過（規格 §7.2）；時間取系統時間
function Write-State([string]$key) {
    try {
        $j = @{ content_type_last = $key; updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz") } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($StatePath, $j, (New-Object Text.UTF8Encoding $false))
    } catch { }
}
# 自訂範本：templates.py list（JSON 一行；只驗證 front matter，不讀內容到 log）
function Get-Templates {
    try {
        $out = @(& $Py -B (Join-Path $Scripts "templates.py") list 2>$null)
        if ($LASTEXITCODE -ne 0 -or $out.Count -eq 0) { return @() }
        $j = ($out | Select-Object -Last 1) | ConvertFrom-Json
        return @($j | ForEach-Object { $_ })     # PowerShell 5.1 的 ConvertFrom-Json 不展開陣列
    } catch { return @() }
}

Write-Host "要轉寫的檔案：" -ForegroundColor Cyan
$Files | ForEach-Object { Write-Host "  $_" }
$preWaits = @()

$defCode = [string](Get-Opt $cfg @("content_type", "default")); if (-not $defCode) { $defCode = "meeting" }
if (-not (Type-Of $defCode)) {
    Write-Host ("config.json 的 content_type.default「{0}」不是內建類型，改用 meeting" -f $defCode) -ForegroundColor Yellow
    $defCode = "meeting"
}
$remember = (Get-Opt $cfg @("content_type", "remember_last")) -ne $false
$tpls = Get-Templates
$items = @()
foreach ($t in $Types) {
    $items += @{ key = $t.code; type = $t.code; menu = $t.label; name = (Short-Label $t.label); noun = $t.noun; skipMain = $t.skipMain
                 template = $null; tplSpeakers = $null }
}
foreach ($t in @($tpls | Where-Object { $_.valid })) {
    $bt = Type-Of ([string]$t.base); if (-not $bt) { continue }
    $items += @{ key = "template:" + $t.code; type = $bt.code; menu = ("{0}［自訂：{1}］" -f $t.name, (Short-Label $bt.label)); name = [string]$t.name
                 noun = ("〈{0}〉{1}" -f $t.name, $bt.noun); skipMain = $bt.skipMain; template = [string]$t.code; tplSpeakers = $t.speakers }
}
$def = $items | Where-Object { $_.key -eq $defCode } | Select-Object -First 1
$defLast = $false; $lastNote = $null
if ($remember) {
    $st = Read-State; $last = [string](Get-Opt $st @("content_type_last"))
    if ($last) {
        $hit = $items | Where-Object { $_.key -eq $last } | Select-Object -First 1
        if ($hit) { $def = $hit; $defLast = $true }
        elseif ($last -like "template:*") {
            $lastNote = "上次選的自訂範本 {0} 已不存在或無法載入，預設改回〈{1}〉" -f $last.Substring(9), $def.name
        }
    }
}
$defName = $def.name; if ($defLast) { $defName = "上次：" + $def.name }
Write-Host ("`n內容類型（Enter＝{0}）" -f $defName) -ForegroundColor Cyan
for ($i = 0; $i -lt 7; $i += 3) {
    $line = "  "
    for ($j = $i; $j -lt [math]::Min($i + 3, 7); $j++) { $line += Pad-Disp ("{0} {1}" -f ($j + 1), $items[$j].menu) 34 }
    Write-Host $line.TrimEnd()
}
for ($j = 7; $j -lt $items.Count; $j++) { Write-Host ("  {0} {1}" -f ($j + 1), $items[$j].menu) }
foreach ($t in @($tpls | Where-Object { -not $_.valid })) { Write-Host ("  ⚠ {0}" -f $t.message) -ForegroundColor Yellow }
if ($lastNote) { Write-Host "  $lastNote" -ForegroundColor Yellow }
$sel = $null; $tA = $null; $tries = 0
while (-not $sel) {
    $r = Ask "請選擇"; if (-not $tA) { $tA = $r[1] }; $tB = $r[2]; $ans = $r[0].Trim(); $tries++
    if (-not $ans) { $sel = $def }
    elseif ($ans -match '^\d+$' -and [int]$ans -ge 1 -and [int]$ans -le $items.Count) { $sel = $items[[int]$ans - 1] }
    elseif ($tries -lt 2) { Write-Host ("沒有這個選項，請輸入 1～{0}，或直接按 Enter" -f $items.Count) -ForegroundColor Yellow }
    else { $sel = $def; Write-Host ("沒有這個選項，使用〈{0}〉" -f $def.name) -ForegroundColor Yellow }
}
$preWaits += , @("ask_type", $tA, $tB)
Write-State $sel.key
Write-Host ("內容類型：{0}" -f $sel.menu)

# 講者人數（規格 §4.4、§4.6、§7.1）：空白＝範本值或自動；1～20＝N；s＝略過說話者分離
$tplSp = [string]$sel.tplSpeakers
if ($tplSp -eq "skip") { $enterTxt = "Enter＝略過（範本設定）" }
elseif ($tplSp -match '^\d+$') { $enterTxt = "Enter＝$tplSp 位（範本設定）" }
else { $enterTxt = "Enter＝自動判斷"; $tplSp = "" }
if ($sel.skipMain) { $spkQ = "講者人數（$enterTxt；填實際人數，不確定就留空；只有一位講者可輸入 s＝略過說話者分離：較快，但字幕時間較不準、提問的學員不會分出來）" }
else { $spkQ = "講者人數（$enterTxt；填實際人數，不確定就留空；輸入 s＝略過說話者分離）" }
$spk = $null; $tA = $null; $tries = 0
while ($null -eq $spk) {
    $r = Ask $spkQ; if (-not $tA) { $tA = $r[1] }; $tB = $r[2]; $ans = $r[0].Trim(); $tries++
    if (-not $ans) { $spk = $tplSp }
    elseif ($ans -match '^[sS]$') { $spk = "skip" }
    elseif ($ans -match '^\d+$' -and [int]$ans -ge 1 -and [int]$ans -le 20) { $spk = [string][int]$ans }
    elseif ($tries -lt 2) { Write-Host "請輸入 1～20 的人數、s（略過說話者分離），或直接按 Enter" -ForegroundColor Yellow }
    else { $spk = $tplSp; Write-Host ("沒有這個選項，使用{0}" -f $enterTxt.Substring(6)) -ForegroundColor Yellow }
}
$preWaits += , @("ask_speakers", $tA, $tB)
$r = Ask "本次專有名詞，逗號分隔（可留空）"; $hot = $r[0]; $preWaits += , @("ask_hotwords", $r[1], $r[2])
$useBreeze = $false
if ($cfg -and $cfg.profiles -and $cfg.profiles.breeze) {
    $r = Ask "使用 Breeze-ASR-25？（中英夾雜很重的技術會議較準，但較慢）[y/N]"; $preWaits += , @("ask_breeze", $r[1], $r[2])
    $useBreeze = $r[0] -match '^[yY]'
}
# 〔2.0.0〕依類型：transcribe.py／auto_minutes.py 的參數、整理的稱呼與輸出檔（規格 §6.2、§7.3）
if ($sel.template) { $TypeArgs = @("--template", $sel.template) } else { $TypeArgs = @("--type", $sel.type) }
$MinLabel = $sel.noun
if ($sel.type -eq "meeting") { $MinFile = "meeting-minutes.md" } else { $MinFile = "notes.md" }

# ------------------------------------------------------------------ 偵測可用的 AI（只找執行檔與 codex login status，不呼叫模型、不耗額度）
# 〔2.4.0〕本機限定時不偵測（不執行 claude／codex 的任何指令）
$hasClaude = $false; $codexExe = $null; $hasCodex = $false; $codexOk = $false
if (-not $LoStart) {
    $hasClaude = [bool](Find-Cli "claude" (Get-Opt $cfg @("correction", "claude", "cli_path")) @(
        (Join-Path $env:USERPROFILE ".local\bin\claude.exe"), (Join-Path $env:APPDATA "npm\claude.cmd")))
    $codexExe = Find-Cli "codex" (Get-Opt $cfg @("correction", "openai", "cli_path")) @(
        (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe"), (Join-Path $env:APPDATA "npm\codex.cmd"))
    $hasCodex = [bool]$codexExe
    if ($hasCodex) { $codexOk = Test-CodexLogin $codexExe }
}
$Vendor = @{ claude = "Claude（Anthropic）"; openai = "GPT（OpenAI）" }   # 〔2.4.0〕「會送到 …」
$PName = @{ claude = "Claude"; openai = "GPT" }
$DefModel = @{ claude = "opus"; openai = "gpt-6.1-sol" }   # 與 common.DEFAULTS 一致

# 這一步（correction／minutes）的預設供應商與模型；不能用時 usable = $false 並附原因（與 auto_correct.select_backend 的規則相同）
function Resolve-Ai([string]$section) {
    $prov = [string](Get-Opt $cfg @($section, "provider")); if (-not $prov) { $prov = "auto" }
    $chan = [string](Get-Opt $cfg @($section, "channel"));  if (-not $chan) { $chan = "cli" }
    $o = @{ section = $section; channel = $chan; provider = ""; model = ""; usable = $false; note = ""; why = "" }
    if ($chan -eq "api") { $canC = [bool]$env:ANTHROPIC_API_KEY; $canO = [bool]$env:OPENAI_API_KEY }
    else { $canC = $hasClaude; $canO = $codexOk }
    $o.canClaude = $canC; $o.canOpenai = $canO
    if ($prov -eq "claude" -and $canC) { $o.provider = "claude" }
    elseif ($prov -eq "openai" -and $canO) { $o.provider = "openai" }
    else {
        if ($prov -in @("claude", "openai")) { $o.note = "設定的 {0} 這次不能用" -f $PName[$prov] }
        # 〔1.1.0〕GPT 優先：已登入的 codex（API 通道：OPENAI_API_KEY）→ GPT（OpenAI）；否則 Claude
        if ($canO) { $o.provider = "openai" }
        elseif ($canC) {
            $o.provider = "claude"
            if ($chan -ne "api" -and $hasCodex) { $o.note = "Codex 尚未登入，這次用 Claude（要用 GPT：在終端機執行 codex login）" }
        }
    }
    if ($o.provider) {
        $o.usable = $true
        $m = [string](Get-Opt $cfg @($section, $o.provider, "model")); if (-not $m) { $m = $DefModel[$o.provider] }
        $o.model = $m
    } elseif ($chan -eq "api") { $o.why = "沒有設定 OPENAI_API_KEY 或 ANTHROPIC_API_KEY" }
    elseif ($hasCodex) { $o.why = "Codex 尚未登入（在終端機執行 codex login），也找不到 claude 指令" }
    else { $o.why = "找不到 claude 或 codex 指令" }
    return $o
}
$AiCorr = Resolve-Ai "correction"
$AiMin = Resolve-Ai "minutes"

# ------------------------------------------------------------------ 〔2.2.0〕參考資料（規格 2.2.0 §7.1、§7.2）
# refs.py plan：只算數量（不抽文字、不跑 ffmpeg、不呼叫模型）；讀不到時當作沒有參考資料（詢問行與 2.1.0 相同）
function Get-RefsPlan([string]$out, [string]$media) {
    try {
        $p = Join-Path $Scripts "refs.py"
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $null }
        $o = @(& $Py -B $p plan $out --media $media 2>$null)
        if ($LASTEXITCODE -ne 0 -or $o.Count -eq 0) { return $null }
        return ($o | Select-Object -Last 1) | ConvertFrom-Json
    } catch { return $null }
}
# 會送出的內容：逐字稿文字、截圖 N 張（只有 AI 校正送圖）、會議文件 M 份的名詞與段落
function Send-What([string]$sec) {
    $parts = @("逐字稿文字")
    $nf = [int](Get-Opt $script:RefsPlan @("frames")); $nd = [int](Get-Opt $script:RefsPlan @("docs"))
    if ($sec -eq "correction" -and $nf -gt 0) { $parts += "截圖 $nf 張" }
    if ($nd -gt 0) { $parts += "會議文件 $nd 份的名詞與段落" }
    return ($parts -join "、")
}
# 背景說明一行（§7.1）：這個檔還沒問過、沒有說明檔與 context.md 時才問；答案放 $script:CtxLine，
# 由第一個答應的步驟以 --context 傳給 Python（寫檔與編碼規則只在 refs.py）
function Ask-Context([string]$out, [string]$provider) {
    if ($script:CtxAsked) { return }
    $script:CtxAsked = $true
    if ((Get-Opt $cfg @("reference", "context")) -eq $false) { return }
    $have = @(@(Get-Opt $script:RefsPlan @("context")) | Where-Object { $_ })
    if ($have.Count -gt 0) { Write-Host ("背景說明：沿用 {0}" -f ($have -join "、")); return }
    if ((Get-Opt $cfg @("reference", "ask_context")) -eq $false) { return }
    $r = Ask ("背景說明（一行，例：會議名稱、與會者全名；會一起送到 {0}，直接 Enter 跳過）" -f $Vendor[$provider])
    Clear-KeyBuffer   # 讀完再清一次：貼上多行時第二行以後留在緩衝區，不得被下一題吃掉
    Log-Wait $out "ask_context" $r[1] $r[2]
    $ans = ([string]$r[0]).Trim()
    if ($ans) { $script:CtxLine = $ans }
}
# 使用者輸入的一行要原樣傳給 Python：Windows PowerShell 5.1／PowerShell 7.2 以前（Legacy 傳參數）不跳脫 " 與結尾的 \，
# 先照 Windows 命令列的規則跳脫（PowerShell 7.3 起預設 Windows 模式，會自己跳脫，原樣傳）
function Legacy-NeedQuotes([string]$s) {          # 與 PowerShell Legacy 模式判斷「要不要加外層引號」的規則相同
    $q = 0; $bs = $false
    foreach ($ch in $s.ToCharArray()) {
        if ($ch -eq '"' -and -not $bs) { $q++ } elseif ([char]::IsWhiteSpace($ch) -and ($q % 2 -eq 0)) { return $true }
        $bs = ($ch -eq '\')
    }
    return $false
}
function Native-Arg([string]$s) {
    $mode = $null; try { $mode = [string](Get-Variable PSNativeCommandArgumentPassing -ValueOnly -ErrorAction Stop) } catch { }
    if (($mode -and $mode -ne "Legacy") -or $s -notmatch '["\\]') { return $s }
    $e = [regex]::Replace($s, '(\\*)"', { param($m) ($m.Groups[1].Value * 2) + '\"' })
    if (Legacy-NeedQuotes $e) { $e = [regex]::Replace($e, '(\\+)$', { param($m) $m.Groups[1].Value * 2 }) }
    return $e
}
# 結束畫面：reference.json 裡讀不到的文件（規格 §2.4、§7.2）
$DocWhy = [ordered]@{ encrypted = "加密"; no_text_layer = "沒有文字層"; unreadable = "讀不了"; too_large = "太大"
                      pdf_lib_missing = "缺 pypdf"; timeout = "逾時"; empty = "沒有文字"; internal_error = "其他" }
function Docs-Unread($ref) {
    $cnt = [ordered]@{}; $n = 0
    foreach ($d in @(Get-Opt $ref @("sources", "docs"))) {
        if (-not $d -or [string](Get-Opt $d @("status")) -eq "ok") { continue }
        $k = ([string](Get-Opt $d @("reason"))).Split(":")[0]
        if (-not $DocWhy.Contains($k)) { continue }
        $w = $DocWhy[$k]
        if ($cnt.Contains($w)) { $cnt[$w] += 1 } else { $cnt[$w] = 1 }
        $n++
    }
    if ($n -eq 0) { return "" }
    return "會議文件 {0} 份沒有讀到（{1}），詳見 reference.json" -f $n, ((@($cnt.Keys) | ForEach-Object { "$_ $($cnt[$_])" }) -join "、")
}
$script:RefsPlan = $null; $script:CtxAsked = $false; $script:CtxLine = $null

# 問一步（AI 校正／會議摘要）並執行；回傳結果 JSON 的 correction／minutes 物件（沒做是 $null）
function Invoke-AiStep($ai, [string]$out, $dur, [string]$runId) {
    $sec = $ai.section
    # 〔2.0.0〕整理的稱呼依類型（規格 §7.3）：會議「會議摘要」；其他「課程筆記」…；自訂範本「〈範本名稱〉會議摘要」
    $label = @{ correction = "AI 校正"; minutes = $MinLabel }[$sec]
    $q = @{ correction = "要做 AI 校正嗎？"; minutes = "要產生${MinLabel}嗎？" }[$sec]
    $askDef = Get-Opt $cfg @($sec, "ask_default"); $yesDef = ($askDef -ne $false)
    $hours = $null; if ($null -ne $dur) { $hours = [double]$dur / 3600 }
    $key = "{0}:{1}" -f $ai.provider, $ai.model
    $what = "{0} {1}" -f $PName[$ai.provider], $ai.model
    if ($ai.note) { Write-Host $ai.note -ForegroundColor Yellow }
    $est = Format-Estimate (Get-Rate $sec $key) $hours
    if ($sec -eq "minutes" -and (Test-Path -LiteralPath (Join-Path $out "transcript.corrected.md"))) { $basis = "依校正版逐字稿整理" } elseif ($sec -eq "minutes") { $basis = "依 transcript.md 整理" } else { $basis = "產出 transcript.corrected.md，原稿不改" }
    $confirmMin = Get-Opt $cfg @("correction", "confirm_over_minutes"); if ($null -eq $confirmMin) { $confirmMin = 120 }
    $send = Send-What $sec                          # 〔2.2.0〕§7.2：依實際要送的內容
    $refsSec = ""; if ($sec -eq "correction" -and [int](Get-Opt $script:RefsPlan @("frames")) -gt 0) { $refsSec = "（截圖整理另約 15～30 秒）" }
    Write-Host ""
    if ($null -ne $dur -and [double]$dur -gt [double]$confirmMin * 60) {
        # 1.1.0 在轉寫前做的長會議確認，1.2.0 改成在這裡把時間與費用寫清楚
        Write-Host ("⚠ 錄音長 {0}：{1}：{2}（{3}）：{4}{5}，會用掉較多額度；{6}會送到 {7}" -f (Format-Duration $dur), $label, $what, $basis, $est, $refsSec, $send, $Vendor[$ai.provider]) -ForegroundColor Yellow
    } else {
        Write-Host ("{0}：{1}（{2}）：{3}{4}；{5}會送到 {6}" -f $label, $what, $basis, $est, $refsSec, $send, $Vendor[$ai.provider])
    }
    $yn = "[Y/n]"; if (-not $yesDef) { $yn = "[y/N]" }
    $r = Ask "$q$yn"; Log-Wait $out "ask_$sec" $r[1] $r[2]
    $ans = $r[0].Trim()
    $yes = $yesDef; if ($ans -match '^[yY]') { $yes = $true } elseif ($ans -match '^[nN]') { $yes = $false }
    if (-not $yes) { Write-Host "略過$label"; return $null }
    Ask-Context $out $ai.provider                  # 〔2.2.0〕§7.1：答應之後、選模型之前（只答應摘要時在摘要這一步問）

    # 選模型：預設以外的推薦模型（順序：另一家的推薦模型 → Claude sonnet；只列能用的）
    # 〔1.2.1〕sonnet 的註記依步驟：校正是「準確率較低」（1.1.0 的校正實測），摘要是「較快」（附錄 F.3 的摘要實測）
    $SonnetNote = @{ correction = "（準確率較低）"; minutes = "（較快，約 sol 1/3 時間；可能漏 1～2 項待辦）" }
    $choices = @()
    foreach ($o in @(
            @{ key = "openai:gpt-6.1-sol"; label = "GPT gpt-6.1-sol"; note = "" },
            @{ key = "claude:opus"; label = "Claude opus"; note = "" },
            @{ key = "claude:sonnet"; label = "Claude sonnet"; note = $SonnetNote[$sec] })) {
        if ($o.key -eq $key) { continue }
        if ($o.key -like "claude:*" -and -not $ai.canClaude) { continue }
        if ($o.key -like "openai:*" -and -not $ai.canOpenai) { continue }
        $choices += $o
    }
    $prov = $ai.provider; $model = $ai.model
    if ($choices.Count -gt 0) {
        if ($null -ne $hours) { $w = "錄音 {0}" -f (Format-Duration $dur) } else { $w = "量不到錄音長度，以下是每小時錄音的數字" }
        Write-Host "${label}用哪個模型？（$w；預估依合成素材實測，實際會議可能不同）" -ForegroundColor Cyan
        Write-Host ("  [Enter] 預設（{0}）：{1}" -f $what, $est)
        $i = 2
        foreach ($o in $choices) {
            $o.n = [string]$i
            Write-Host ("  [{0}] {1}{2}：{3}" -f $i, $o.label, $o.note, (Format-Estimate (Get-Rate $sec $o.key) $hours))
            $i++
        }
        if ($ai.channel -eq "api") { Write-Host "  費用是 API 等價估算；API 通道依實際用量付費" }
        else { Write-Host "  費用是 API 等價估算：用訂閱時不另計費，但會用掉額度" }
        $r = Ask "請選擇"; Log-Wait $out "choose_$sec" $r[1] $r[2]
        $ans = $r[0].Trim()
        $pick = $choices | Where-Object { $_.n -eq $ans } | Select-Object -First 1
        if ($pick) { $prov, $model = $pick.key.Split(":", 2) }
        elseif ($ans) { Write-Host "沒有這個選項，使用預設" -ForegroundColor Yellow }
    }
    Write-Host ("{0}：{1} {2}；{3}會送到 {4}" -f $label, $PName[$prov], $model, $send, $Vendor[$prov])
    if ($sec -eq "correction") { $argList = @((Join-Path $Scripts "auto_correct.py"), $out, "--force", "--correct-provider", $prov, "--correct-model", $model) }
    else { $argList = @((Join-Path $Scripts "auto_minutes.py"), $out, "--force") + $TypeArgs + @("--minutes-provider", $prov, "--minutes-model", $model) }
    if ($script:CtxLine) { $argList += @("--context", (Native-Arg $script:CtxLine)); $script:CtxLine = $null }   # 〔2.2.0〕陣列傳參數（" $ ` \ 都原樣）
    $stdout = @(& $Py @argList)          # 進度寫在 stderr（直接顯示）；stdout 最後一行是 JSON 摘要
    $res = $null
    try { $res = (($stdout | Select-Object -Last 1) | ConvertFrom-Json).$sec } catch { }
    $st = [string](Get-Opt $res @("status")); $rs = [string](Get-Opt $res @("reason"))
    if ($st -eq "partial") {
        if ($sec -eq "correction") { Write-Host ("AI 校正部分完成（{0}/{1} 段，原因：{2}），其餘段落保留原文" -f $res.chunks_ok, $res.chunks, $rs) -ForegroundColor Yellow }
        else { Write-Host ("{3}部分完成（{0}/{1} 段，原因：{2}），請看 {4} 開頭的說明" -f $res.parts_ok, $res.parts, $rs, $MinLabel, $MinFile) -ForegroundColor Yellow }
    } elseif ($st -ne "ok") {
        if ($rs -eq "auth_failed") {
            if ($prov -eq "openai") { Write-Host "Codex 尚未登入，${label}未完成：在終端機執行 codex login 後可再試" -ForegroundColor Yellow }
            else { Write-Host "Claude Code 尚未登入，${label}未完成：在終端機執行 claude 並輸入 /login 後可再試" -ForegroundColor Yellow }
        } else {
            $j = @{ correction = "auto_correct.json"; minutes = "auto_minutes.json" }[$sec]
            Write-Host "${label}未完成（$st：$rs），詳見輸出資料夾的 $j" -ForegroundColor Yellow
        }
    }
    return $res
}

$Thing = "會議記錄"; if ($sel.type -ne "meeting") { $Thing = (Type-Of $sel.type).noun }
$NoAiHint = @(
    "要用 AI 校正與${MinLabel}：安裝 Codex（codex 指令，執行 codex login）或 Claude Code（claude 指令，執行 claude 後輸入 /login），",
    "之後可以對輸出資料夾執行 auto_correct.py、auto_minutes.py 補做；或在 Claude 對話中說「用 meeting-minutes-pro 整理這份${Thing}」並附上 transcript.md。")
# 字幕的條數說明（transcribe.py 的 subtitles.cues、auto_correct.py 的 correction.subtitles；規格 §7.4）
function Cue-Note($s, [bool]$corrected) {
    $st = [string](Get-Opt $s @("status"))
    if (-not $st) { return "" }
    if ($st -eq "ok" -or $st -eq "map_failed") {
        $t = "{0} 條" -f (Get-Opt $s @("cues"))
        if ($corrected) {
            if ($st -eq "map_failed") { $t += "，對應失敗，全部用原文" }
            else { $t += "，對應失敗 {0} 段" -f [int](Get-Opt $s @("map_failed_paragraphs")) }
        }
        return "（$t）"
    }
    if ($st -eq "skipped") { return "" }
    return "（產生失敗：$([string](Get-Opt $s @('reason')))）"
}

$first = $true
foreach ($f in $Files) {
    $runId = [guid]::NewGuid().ToString("N").Substring(0, 12)
    $env:MMP_RUN_ID = $runId
    $argList = @((Join-Path $Scripts "transcribe.py"), $f, "--no-correct") + $TypeArgs   # 1.2.0：校正改在轉寫完成後詢問
    if ($LocalOnly) { $argList += "--local-only" }      # 〔2.4.0〕本機限定入口：輸出資料夾寫標記檔
    if ($spk -eq "skip") { $argList += "--no-diarize" }
    elseif ($spk -match '^\d+$') { $argList += @("--speakers", $spk) }
    if ($hot) { $argList += @("--hotwords", (Native-Arg $hot)) }   # 〔2.3.0〕同 --context：PowerShell 5.1 遇到 " 與結尾 \ 也原樣傳
    if ($useBreeze) { $argList += @("--whisper", "breeze") }
    Write-Host "`n=== $f ===" -ForegroundColor Cyan
    $stdout = @(& $Py @argList)          # 進度寫在 stderr（直接顯示）；stdout 最後一行是 JSON 摘要
    $code = $LASTEXITCODE
    $stdout | Select-Object -SkipLast 1 | ForEach-Object { Write-Host $_ }
    $res = $null
    try { $res = ($stdout | Select-Object -Last 1) | ConvertFrom-Json } catch { }
    $item = Get-Item -LiteralPath $f
    $out = Join-Path $item.DirectoryName ($item.BaseName + "_minutes")
    if ($res -and $res.out_dir) { $out = $res.out_dir }
    if ($first) { foreach ($w in $preWaits) { Log-Wait $out $w[0] $w[1] $w[2] }; $first = $false }
    if ($code -ne 0) {
        Write-Host "轉寫失敗（exit $code）" -ForegroundColor Red
        & $Py (Join-Path $Scripts "runlog.py") finish $out --run-id $runId 2>$null | Out-Null
        continue
    }
    Write-Host "`n逐字稿完成：$out" -ForegroundColor Green
    $dur = $null; if ($res -and $null -ne $res.duration) { $dur = [double]$res.duration } else { $dur = Get-Duration $f }

    $corr = $null; $mins = $null
    $script:RefsPlan = $null; $script:CtxAsked = $false; $script:CtxLine = $null   # 〔2.2.0〕每個檔各問一次背景說明
    # 〔2.4.0〕本機限定：入口或全域設定，或這份的輸出資料夾已有標記檔 → 不問 AI 校正與整理
    $lo = $LoStart -or (Test-Path -LiteralPath (Join-Path $out $LocalOnlyMarker) -PathType Leaf)
    if (-not $lo -and ($AiCorr.usable -or $AiMin.usable)) { $script:RefsPlan = Get-RefsPlan $out $item.FullName }
    if ($lo) {
        Write-Host ("本機限定：不做 AI 校正與{0}，不會送出任何資料" -f $MinLabel) -ForegroundColor Yellow
    } elseif (-not $AiCorr.usable -and -not $AiMin.usable) {
        Write-Host ("{0}：略過 AI 校正與{1}。" -f $AiCorr.why, $MinLabel) -ForegroundColor Yellow
        $NoAiHint | ForEach-Object { Write-Host "  $_" }
    } else {
        if ($AiCorr.usable) { $corr = Invoke-AiStep $AiCorr $out $dur $runId } else { Write-Host ("{0}：略過 AI 校正" -f $AiCorr.why) -ForegroundColor Yellow }
        if ($AiMin.usable) { $mins = Invoke-AiStep $AiMin $out $dur $runId } else { Write-Host ("{0}：略過{1}" -f $AiMin.why, $MinLabel) -ForegroundColor Yellow }
    }
    & $Py (Join-Path $Scripts "runlog.py") finish $out --run-id $runId 2>$null | Out-Null

    # ------------------------------------------------------------------ 結束畫面：產出的檔案與 log 位置
    Write-Host "`n完成：$out" -ForegroundColor Green
    $cueNote = Cue-Note (Get-Opt $res @("subtitles", "cues")) $false
    $corNote = Cue-Note (Get-Opt $corr @("subtitles")) $true
    # 〔2.1.0〕網頁版：auto_minutes.json 的 html（status ok 且檔案在才列；html.enabled 關或沒有產生時不列）
    $html = $null
    try { $html = (Get-Content -LiteralPath (Join-Path $out "auto_minutes.json") -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json).html } catch { }
    $htmlFile = [string](Get-Opt $html @("output"))
    if ([string](Get-Opt $html @("status")) -ne "ok" -or -not $htmlFile -or -not (Test-Path -LiteralPath (Join-Path $out $htmlFile))) { $htmlFile = "" }
    $tcNote = "時間碼為文字"; if (@("found", "explicit") -contains [string](Get-Opt $html @("media"))) { $tcNote = "時間碼可點播放" }
    foreach ($x in @(
            @("meeting-minutes.md", "會議記錄（AI 自動整理，未經人工確認）"),
            @("meeting-minutes.html", "會議記錄網頁版（用瀏覽器開；$tcNote）"),
            @("notes.md", "${Thing}（AI 自動整理，未經人工確認）"),
            @("notes.html", "${Thing}網頁版（用瀏覽器開；$tcNote）"),
            @("notes.json", "筆記的結構化資料（改過後執行 auto_minutes.py --render-only 重新產生 notes.md）"),
            @("transcript.corrected.md", "校正版逐字稿（AI 校正，標出每一處修改）"),
            @("corrections.suggested.tsv", "對照表建議（尚未生效）"),
            @("reference.json", "參考資料整理（AI 從截圖、文件認出的與會者與名詞）"),
            @("context.md", "背景說明（重跑時沿用）"),
            @("transcript.md", "逐字稿（原稿）"),
            @("transcript.srt", "字幕檔（一段一條）"),
            @("transcript.cues.srt", "字幕（依字幕規則切條，不經 AI）$cueNote"),
            @("transcript.corrected.srt", "校正版字幕$corNote"),
            @("frames", "影片截圖"),
            @($LocalOnlyMarker, "本機限定標記（刪掉這個檔＝解除這一份的本機限定）"))) {
        if ($x[0] -like "*.html" -and $x[0] -ne $htmlFile) { continue }
        if (Test-Path -LiteralPath (Join-Path $out $x[0])) { Write-Host ("  {0,-26} {1}" -f $x[0], $x[1]) }
    }
    Write-Host "  執行 log：$(Join-Path $out 'run_log.jsonl')"
    Write-Host "  歷次執行摘要：$(Join-Path $MMH 'logs\runs.jsonl')（彙整：`"$Py`" `"$(Join-Path $Scripts 'runlog.py')`" summary）"
    # 〔2.0.0〕說話者分離退回 CPU 的原因、零星講者（transcript.json 的 meta；規格 §4.5、§4.7、§7.4）
    $meta = $null
    try { $meta = (Get-Content -LiteralPath (Join-Path $out "transcript.json") -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json).meta } catch { }
    $fb = [string](Get-Opt $meta @("diarization", "fallback"))
    if ($fb) {
        $why = $fb
        try { $t = @(& $Py -B -c "import sys; sys.path.insert(0, sys.argv[1]); import diarize; print(diarize.reason_text(sys.argv[2]))" $Scripts $fb 2>$null); if ($LASTEXITCODE -eq 0 -and $t) { $why = [string]($t | Select-Object -Last 1) } } catch { }
        Write-Host "說話者分離改用 CPU（sherpa）：$why" -ForegroundColor Yellow
    }
    $minor = @(@(Get-Opt $meta @("speaker_stats")) | Where-Object { $_ -and $_.minor } | ForEach-Object { [string]$_.speaker })
    if ($minor.Count -gt 0) {
        Write-Host ("講者 {0} 發言很少，可能是分離誤判（見 transcript.md 表頭）；確定人數時可重跑並填人數" -f ($minor -join "、")) -ForegroundColor Yellow
    }
    $hasCorr = Test-Path -LiteralPath (Join-Path $out "transcript.corrected.md")
    $srcName = "transcript.md"; if ($hasCorr) { $srcName = "transcript.corrected.md" }
    # 〔2.2.0〕參考資料：讀不到的文件（黃字）；有 reference.json 時「下一步」改說截圖已在 AI 校正時參考（§7.2、§9.1）
    $refj = $null
    if (Test-Path -LiteralPath (Join-Path $out "reference.json") -PathType Leaf) {
        try { $refj = Get-Content -LiteralPath (Join-Path $out "reference.json") -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json } catch { }
    }
    $unread = Docs-Unread $refj
    if ($unread) { Write-Host $unread -ForegroundColor Yellow }
    $shotNote = "影片可一併附上 frames 內的截圖"
    if (Test-Path -LiteralPath (Join-Path $out "reference.json")) { $shotNote = "影片截圖已在 AI 校正時參考，認出的與會者在 reference.json" }
    # 〔2.1.0〕這次有整理、但網頁版沒產生（failed）：黃字說明原因與補做的指令
    if ($mins -and [string](Get-Opt $html @("status")) -eq "failed") {
        $hr = [string](Get-Opt $html @("reason"))
        $hw = @{ template_missing = "找不到網頁版樣板 html_template.html"; write_failed = "寫入檔案失敗"; internal_error = "程式錯誤" }[$hr]
        if (-not $hw) { $hw = $hr }
        Write-Host ("網頁版未產生（{0}）；可執行 render_html.py 補做：`"{1}`" `"{2}`" `"{3}`"" -f $hw, $Py, (Join-Path $Scripts "render_html.py"), $out) -ForegroundColor Yellow
    }
    if ($lo) {
        # 〔2.4.0〕本機限定：不提示在 Claude 對話中整理（那會把內容送出去）；改提示用會議記錄校稿人工校稿
        Write-Host "本機限定：沒有送出任何資料（沒有 AI 校正，也沒有 AI 整理）。" -ForegroundColor Green
        Write-Host "下一步：要人工校稿，對這個輸出資料夾按右鍵 → 傳送到 → 會議記錄校稿（Pro 的附屬工具，另外安裝）；校稿得到的經驗匯入對照表與詞表後，下次轉寫更準。"
        $how = @()
        if (Test-Path -LiteralPath (Join-Path $out $LocalOnlyMarker) -PathType Leaf) { $how += "這一份：刪除輸出資料夾裡的 $LocalOnlyMarker" }
        if ($LoCfg) { $how += "全部：把 $(Join-Path $MMH 'config.json') 的 privacy.local_only 改成 false" }
        if ($how.Count -gt 0) { Write-Host ("要解除本機限定（之後才能用 AI 校正與整理）：{0}" -f ($how -join "；")) }
    } elseif (Test-Path -LiteralPath (Join-Path $out "meeting-minutes.md")) {
        $open = "meeting-minutes.md "; if ($htmlFile -eq "meeting-minutes.html") { $open = "meeting-minutes.html（用瀏覽器）" }
        Write-Host "下一步：打開 ${open}確認決議與待辦；要補講者姓名或修改，在 Claude 中說「用 meeting-minutes-pro 檢查這份會議記錄」，附上 meeting-minutes.md 與$(if ($hasCorr) { ' transcript.corrected.md' } else { ' transcript.md' })。"
    } elseif ($sel.type -ne "meeting" -and (Test-Path -LiteralPath (Join-Path $out "notes.md"))) {
        $open = "notes.md "; if ($htmlFile -eq "notes.html") { $open = "notes.html（用瀏覽器）" }
        Write-Host "下一步：打開 ${open}確認內容；要補講者姓名或修改，在 Claude 中說「用 meeting-minutes-pro 檢查這份${Thing}」，附上 notes.md 與 ${srcName}。"
    } elseif ($hasCorr) {
        Write-Host "下一步：在 Claude 中說「用 meeting-minutes-pro 整理這份${Thing}」，附上 transcript.corrected.md（已自動校正，只剩待確認與講者對應；${shotNote}）。"
    } else {
        Write-Host "下一步：在 Claude 中說「用 meeting-minutes-pro 整理這份${Thing}，並產生校正版逐字稿」，附上 transcript.md（${shotNote}）。"
    }
    if (-not $env:MMP_TEST_NO_OPEN) { Start-Process explorer.exe $out }   # MMP_TEST_NO_OPEN：僅供開發測試，不開資料夾
}
Remove-Item Env:MMP_RUN_ID -ErrorAction SilentlyContinue
Clear-KeyBuffer   # 〔1.2.2〕處理中誤按的 Enter 不會讓視窗在結束時直接關閉
Read-Host "`n按 Enter 關閉"
