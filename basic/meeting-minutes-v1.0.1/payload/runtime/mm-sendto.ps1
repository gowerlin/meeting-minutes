# 檔案總管右鍵「傳送到 → 會議轉寫（基本版）」的執行腳本（meeting-minutes 1.0.1）
# 1.0.1：讀檔的 cmdlet 加 -ErrorAction Stop。Get-Content 找不到檔案是「非終止錯誤」，try/catch 抓不到，
#        會在主控台印紅字（比照 Pro 2.0.1）。現在讀不到、壞掉的 config.json 都安靜地略過那一行
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
# 本腳本由安裝程式放在 runtime 根目錄（1.0.1 起以本腳本所在位置為準，-TestRoot 試裝時才會用到測試位置）
$MMH = $PSScriptRoot
if (-not $MMH) { $MMH = Split-Path -Parent $MyInvocation.MyCommand.Path }
# 使用者自己設定了 MEETING_MINUTES_HOME（把模型放到其他磁碟）時照舊沿用；沒設定時讓轉寫腳本用本腳本所在的位置
if (-not $env:MEETING_MINUTES_HOME) { $env:MEETING_MINUTES_HOME = $MMH }
$Py = Join-Path $MMH "venv\Scripts\python.exe"
$Script = Join-Path $MMH "scripts\transcribe.py"
$Host.UI.RawUI.WindowTitle = "會議轉寫（基本版）"
Write-Host "==== 會議轉寫（基本版）　skill：meeting-minutes ====" -ForegroundColor Magenta
$cfgPath = Join-Path $MMH "config.json"
if (Test-Path -LiteralPath $cfgPath) {
    try {
        $c = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        Write-Host ("後端：{0} / {1}　模型：{2}" -f $c.backend, $c.device, $c.whisper)
    } catch { }
}

if (-not (Test-Path $Py)) { Write-Host "尚未安裝 runtime，請重新執行 install.cmd" -ForegroundColor Red; Read-Host "按 Enter 關閉"; exit 1 }
if (-not $Files -or $Files.Count -eq 0) { Write-Host "請在檔案總管對錄音或錄影檔按右鍵 → 傳送到 → 會議轉寫（基本版）"; Read-Host "按 Enter 關閉"; exit 1 }

Write-Host "要轉寫的檔案：" -ForegroundColor Cyan
$Files | ForEach-Object { Write-Host "  $_" }
$spk = Read-Host "`n與會人數（直接 Enter = 自動判斷）"
$hot = Read-Host "本次專有名詞，逗號分隔（可留空）"

foreach ($f in $Files) {
    $argList = @($Script, $f)
    if ($spk -match '^\d+$') { $argList += @("--speakers", $spk) }
    if ($hot) { $argList += @("--hotwords", $hot) }
    Write-Host "`n=== $f ===" -ForegroundColor Cyan
    & $Py @argList
    if ($LASTEXITCODE -eq 0) {
        $out = $null
        try {
            $item = Get-Item -LiteralPath $f -ErrorAction Stop
            $out = Join-Path $item.DirectoryName ($item.BaseName + "_minutes")
        } catch { }
        Write-Host "`n完成：$out" -ForegroundColor Green
        Write-Host "下一步：在 Claude 中說「用 meeting-minutes 整理這份會議記錄」，並附上 transcript.md（影片可一併附上 frames 內的截圖）。"
        # MM_TEST_NO_OPEN=1：僅供開發測試，完成後不開啟輸出資料夾（1.0.1，比照 Pro 的 MMP_TEST_NO_OPEN）
        if ($out -and (Test-Path -LiteralPath $out) -and $env:MM_TEST_NO_OPEN -ne "1") { Start-Process explorer.exe $out }
    } else {
        Write-Host "轉寫失敗（exit $LASTEXITCODE）" -ForegroundColor Red
    }
}
Read-Host "`n按 Enter 關閉"
