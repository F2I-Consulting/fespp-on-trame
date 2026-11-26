# Browser smoke test for fespp-on-trame.
# Usage:
#   .\test-browser.ps1                      -> run every scenario against a fresh container
#   .\test-browser.ps1 -Scenario tree       -> run one scenario (file name fragment)
#   .\test-browser.ps1 -Headed              -> watch the browser instead of headless
#   .\test-browser.ps1 -Keep                -> leave the container running afterwards
#   .\test-browser.ps1 -Reuse               -> drive the container already running (no injection)
#
# What it does that the headless harness (test-visual.ps1) cannot: it runs the
# WIDGETS' JavaScript. The scenarios open a real Chromium on the application,
# load a file, walk the tree, its context menu, the tool cards, every panel of
# the top bar and the Statistics view, and fail on the first console error, failed
# request, unresolved component or empty panel.
#
# The container serves the LOCAL source tree (tests\browser\instance.ps1
# injects the app package, the widget packages and their JS bundles, with no
# rebuild), so what is tested is the working tree, not the image.
#
# Traces and failure screenshots land in tests\browser\out\ (gitignored).

param(
    [string]$Scenario = "all",
    [switch]$Headed,
    [switch]$Keep,
    [switch]$Reuse,
    [int]$Port = 8095,
    [string]$Name = "fespp_smoke",
    [string]$Image = "fespp_on_trame:local",
    # Optional: open a file at startup instead of going through Import data.
    # The scenarios import the file themselves, so this is for hand-driving.
    [string]$Epc = ""
)

# NOT "Stop": with EAP=Stop any native command writing to stderr (docker rm on
# a container that is not there) raises a terminating NativeCommandError in
# PowerShell 5.1. Failures are handled through exit codes below.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$browserDir = Join-Path $root "tests\browser"
$specDir = Join-Path $browserDir "specs"
$outDir = Join-Path $browserDir "out"
$url = "http://localhost:$Port/index.html"

function Get-ScenarioName($file) { $file.Name -replace '^\d+-', '' -replace '\.spec\.mjs$', '' }

$all = Get-ChildItem $specDir -Filter *.spec.mjs
$specs = $all
if ($Scenario -ne "all") {
    $specs = $all | Where-Object { (Get-ScenarioName $_) -like "*$Scenario*" }
    if (-not $specs) {
        Write-Host "Unknown scenario: $Scenario" -ForegroundColor Red
        Write-Host "Known: $((($all | ForEach-Object { Get-ScenarioName $_ })) -join ', ')"
        exit 1
    }
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] node/npx not found on this machine." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $browserDir "node_modules"))) {
    Write-Host "Installing the browser driver (once)..." -ForegroundColor Cyan
    Push-Location $browserDir
    npm install --silent
    npx playwright install chromium
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] install failed" -ForegroundColor Red; exit 1 }
}

# --- the charter gate, before any container is started --------------------
# The same eslint run as widgets/lint.sh (which needs a POSIX shell): a widget
# that draws its own button, select, number field or empty state fails here,
# in seconds, rather than minutes later in the components sweep
# (specs/04c-components).
# Run FROM widgets/, on relative paths: the config's exemptions are
# `overrides[].files` globs, which eslint matches against paths relative to
# the working directory; from the repo root none of them matches, and the
# shared components get flagged for the very patterns they implement.
$widgets = Join-Path $root "widgets"
$eslint = Join-Path $widgets "tree\vue-components\node_modules\eslint\bin\eslint.js"
if (Test-Path $eslint) {
    Push-Location $widgets
    $lintDirs = @(Get-ChildItem "*\vue-components\src" -Directory | ForEach-Object {
        Resolve-Path -Relative $_.FullName })
    $lintDirs += "_shared"
    & node $eslint --no-eslintrc -c .eslintrc.widgets.json `
        --resolve-plugins-relative-to tree\vue-components --ext .js,.vue `
        --ignore-pattern "**/node_modules/**" --ignore-pattern "**/serve/**" --ignore-pattern "**/dist/**" `
        @lintDirs
    $lintExit = $LASTEXITCODE
    Pop-Location
    if ($lintExit -ne 0) {
        Write-Host "WIDGET LINT: FAIL (the charter gate, widgets/.eslintrc.widgets.json)" -ForegroundColor Red
        exit 1
    }
    Write-Host "Widget lint: clean ($($lintDirs.Count) source trees)" -ForegroundColor Green
} else {
    Write-Host "[WARN] widgets/tree has no node_modules: the charter gate did not run" -ForegroundColor Yellow
}

# --- the application under test -------------------------------------------
$started = $false
if ($Reuse) {
    $running = docker inspect -f "{{.State.Running}}" $Name 2>$null
    if ($running -ne "true") {
        Write-Host "[ERROR] -Reuse: container $Name is not running" -ForegroundColor Red
        exit 1
    }
    Write-Host "Reusing $Name on $url (local code NOT re-injected)" -ForegroundColor Yellow
} else {
    $instance = @{ Port = $Port; Name = $Name; Image = $Image }
    if ($Epc) { $instance.Epc = $Epc }
    & (Join-Path $browserDir "instance.ps1") @instance
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $started = $true
}

# Apache answers before the application does: the first page load starts the
# ParaView session, which the scenarios wait for themselves.
$alive = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        if ((Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
            $alive = $true; break
        }
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $alive) {
    Write-Host "[ERROR] no answer on $url" -ForegroundColor Red
    if ($started -and -not $Keep) { docker rm -f $Name 2>$null | Out-Null }
    exit 1
}

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
New-Item -ItemType Directory -Force $outDir | Out-Null

$env:FESPP_SMOKE_URL = $url
if ($Headed) { $env:FESPP_SMOKE_HEADED = "1" } else { $env:FESPP_SMOKE_HEADED = $null }

# ONE run for every selected scenario: they share a single browser session, so
# splitting the run per file would open one ParaView session per scenario.
$files = @($specs | ForEach-Object { "specs/" + $_.Name })
Write-Host ""
Write-Host "=== scenarios: $((($specs | ForEach-Object { Get-ScenarioName $_ })) -join ', ') ===" -ForegroundColor Cyan
Push-Location $browserDir
npx playwright test $files
$anyFail = ($LASTEXITCODE -ne 0)
Pop-Location

# The application's own log of the run: the launcher writes one file per
# session. An exception of a bug type raised inside the app fails the run
# even when a handler swallowed it (the strict reporter of engine/strict.py,
# armed by instance.ps1): one line per site, "[fespp-strict] NameError: ...".
$appLog = Join-Path $outDir "app.log"
docker exec $Name sh -c "cat /deploy/server/logs/launcher/*.txt 2>/dev/null" > $appLog 2>$null
$strictSites = @(Get-Content $appLog -ErrorAction SilentlyContinue | Select-String -Pattern "^\[fespp-strict\] [A-Za-z]+(Error|Exception): ")
if ($strictSites.Count -gt 0) {
    Write-Host ""
    Write-Host "STRICT: $($strictSites.Count) exception site(s) raised inside the app (see $appLog)" -ForegroundColor Red
    foreach ($line in $strictSites | Select-Object -First 8) { Write-Host "    $($line.Line)" -ForegroundColor Red }
    $anyFail = $true
} elseif (-not (Get-Content $appLog -ErrorAction SilentlyContinue | Select-String -Pattern "fespp-strict\] armed" -Quiet)) {
    Write-Host ""
    Write-Host "[WARN] the strict reporter did not report itself armed in the session log ($appLog)" -ForegroundColor Yellow
}

if ($started -and -not $Keep) {
    docker rm -f $Name 2>$null | Out-Null
} elseif ($Keep) {
    Write-Host ""
    Write-Host "Container kept: $url  (stop it with .\tests\browser\instance.ps1 -Stop -Name $Name)" -ForegroundColor Gray
}

Write-Host ""
if ($anyFail) {
    Write-Host "Traces and screenshots: $outDir" -ForegroundColor Gray
    Write-Host "BROWSER TESTS: FAIL" -ForegroundColor Red
    exit 1
}
Write-Host "BROWSER TESTS: PASS" -ForegroundColor Green
exit 0
