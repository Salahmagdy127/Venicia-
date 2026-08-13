# فينيسيا — تشغيل النظام
#
#   دبل كليك على launch.vbs  →  بيشتغل من غير أي شباك أسود.
#   .\launch.ps1 -Visible     →  نفس الحاجة بس بتشوف الرسايل (للتشخيص).
#   .\launch.ps1 -Rebuild     →  يعيد بناء الواجهة بالعافية.
#
# النظام كله بيتقدّم من سيرفر واحد: FastAPI بيقدّم الـ API والواجهة المبنية
# مع بعض. مفيش node شغال، ومفيش بروكسي، والصفحات جاهزة مش بتتترجم لحظياً.
# بيتفتح في شباك لوحده، وأول ما تقفله السيرفر بيتقفل معاه.

param([switch]$Visible, [switch]$Rebuild)

$ErrorActionPreference = "Stop"

$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python   = Join-Path $backend ".venv\Scripts\python.exe"
$vite     = Join-Path $frontend "node_modules\vite\bin\vite.js"
$dist     = Join-Path $frontend "dist\index.html"
$db       = Join-Path $backend "venicia.db"
$profile_ = Join-Path $env:LOCALAPPDATA "Venicia\browser"
$logDir   = Join-Path $env:LOCALAPPDATA "Venicia\logs"
$log      = Join-Path $logDir "launch.log"

$APP = "http://127.0.0.1:8000/"

function Say([string]$text, [string]$color = "Gray") {
    "$(Get-Date -Format 'HH:mm:ss')  $text" | Out-File -FilePath $log -Append -Encoding utf8
    if ($Visible) { Write-Host "  $text" -ForegroundColor $color }
}

function Fail([string]$text) {
    Say "خطأ: $text"
    if ($Visible) {
        Write-Host "  $text" -ForegroundColor Red
        Read-Host "`n  اضغط Enter للخروج"
    } else {
        (New-Object -ComObject WScript.Shell).Popup($text, 0, "فينيسيا", 16) | Out-Null
    }
    exit 1
}

function Test-Ready([int]$sec = 2) {
    try { Invoke-WebRequest -Uri "$APP`health" -UseBasicParsing -TimeoutSec $sec | Out-Null; return $true }
    catch { return $false }
}

function Find-Browser {
    # لازم متصفح Chromium عشان وضع التطبيق — شباك بلا تبويبات ولا شريط عنوان
    foreach ($path in @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )) { if ($path -and (Test-Path $path)) { return $path } }
    return $null
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
"" | Out-File -FilePath $log -Encoding utf8

if ($Visible) {
    Write-Host ""
    Write-Host "  فينيسيا · Venicia Resort Suite" -ForegroundColor Cyan
    Write-Host "  ------------------------------" -ForegroundColor DarkCyan
}

# ═══════════════════════════════════════════════ فحص المتطلبات
if (-not (Test-Path $python)) {
    Fail "بايثون مش متجهّز.`n`nافتح PowerShell في فولدر المشروع وشغّل:`n  cd backend`n  python -m venv .venv`n  .\.venv\Scripts\pip install -r requirements.txt"
}

if (-not (Test-Path $db)) {
    Say "قاعدة البيانات مش موجودة — بنجهّزها في شباك ظاهر" "Yellow"
    $seed = "Set-Location '$backend'; " +
            "Write-Host '  بنجهّز قاعدة البيانات — دقيقتين تقريباً...' -ForegroundColor Yellow; " +
            "& '$python' -m scripts.seed_master; " +
            "& '$python' -m scripts.seed_history; " +
            "& '$python' -m scripts.seed_live"
    Start-Process powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-Command",$seed -Wait
    if (-not (Test-Path $db)) { Fail "تجهيز قاعدة البيانات فشل." }
}

# ═══════════════════════════════════════════════ بناء الواجهة عند اللزوم
# بنبني بس لو مفيش نسخة أو لو الكود اتغيّر بعد آخر بناء
$needsBuild = $Rebuild -or -not (Test-Path $dist)
if (-not $needsBuild) {
    $built = (Get-Item $dist).LastWriteTimeUtc
    $sources = @(
        Get-ChildItem (Join-Path $frontend "src") -Recurse -File
        Get-ChildItem $frontend -File -Filter "*.ts"
        Get-ChildItem $frontend -File -Filter "*.json"
        Get-ChildItem $frontend -File -Filter "index.html"
    )
    $newest = ($sources | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1)
    if ($newest -and $newest.LastWriteTimeUtc -gt $built) {
        Say "الكود اتغيّر بعد آخر بناء ($($newest.Name))"
        $needsBuild = $true
    }
}

if ($needsBuild) {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { Fail "Node.js مش متسطّب — محتاجينه عشان نبني الواجهة." }
    if (-not (Test-Path $vite)) { Fail "حزم الواجهة مش متثبّتة.`n`n  cd frontend`n  npm install" }

    Say "بنبني الواجهة..." "Yellow"
    $build = Start-Process -FilePath $node.Source -ArgumentList "`"$vite`"","build" `
        -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput (Join-Path $logDir "build.log") `
        -RedirectStandardError  (Join-Path $logDir "build.err")
    if ($build.ExitCode -ne 0 -or -not (Test-Path $dist)) {
        Fail "بناء الواجهة فشل.`n`nالتفاصيل في:`n$logDir\build.err"
    }
    Say "الواجهة اتبنت"
}

# ═══════════════════════════════════════════════ تشغيل السيرفر
$ours = @()
if (Test-Ready) {
    Say "النظام شغال بالفعل"
} else {
    Say "بنشغّل السيرفر..."
    $ours += (Start-Process -FilePath $python `
        -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" `
        -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "server.log") `
        -RedirectStandardError  (Join-Path $logDir "server.err")).Id

    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 250
        if (Test-Ready 1) { $ready = $true; break }
    }
    if (-not $ready) {
        foreach ($processId in $ours) { & taskkill /PID $processId /T /F 2>$null | Out-Null }
        Fail "السيرفر مافتحش.`n`nالتفاصيل في:`n$logDir\server.err"
    }
}

# ═══════════════════════════════════════════════ فتح النظام
Say "جاهز — بنفتح النظام" "Green"

function Count-Windows {
    # بنعدّ عمليات المتصفح اللي شغالة على بروفايل فينيسيا. مبنعتمدش على
    # العملية اللي احنا شغّلناها، لأن المتصفح ساعات بيسلّم الشباك لنسخة
    # شغالة قبل كده ويقفل نفسه فوراً.
    $procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" `
        -ErrorAction SilentlyContinue
    return @($procs | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile_) }).Count
}

$browser = Find-Browser
if ($browser) {
    # بروفايل مستقل: بيدّي شباك نضيف، وبيفصلنا عن نسخة المتصفح العادية
    Start-Process -FilePath $browser -ArgumentList @(
        "--app=$APP",
        "--user-data-dir=$profile_",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized"
    ) | Out-Null

    Say "لما تقفل الشباك، النظام هيقفل لوحده"

    # نستنى الشباك يبان الأول (المتصفح البارد بياخد لحظة)
    foreach ($i in 1..40) {
        if ((Count-Windows) -gt 0) { break }
        Start-Sleep -Milliseconds 250
    }
    # وبعدين نفضل مستنيين لحد ما كل شبابيك فينيسيا تتقفل
    while ((Count-Windows) -gt 0) { Start-Sleep -Seconds 2 }

    if ($ours.Count -gt 0) {
        Say "الشباك اتقفل — بنقفل النظام" "Yellow"
        foreach ($processId in $ours) { & taskkill /PID $processId /T /F 2>$null | Out-Null }
        Say "تم" "Green"
    } else {
        Say "الشباك اتقفل — السيرفر كان شغال قبلنا فسايبينه" "Yellow"
    }
} else {
    Start-Process $APP
    Say "مفيش Edge ولا Chrome — النظام هيفضل شغال" "Yellow"
}

if ($Visible) { Write-Host "" }
