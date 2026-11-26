# One disposable app instance for a browser-driven run: its own container, on
# its own port, serving the LOCAL source tree (no image rebuild).
#
#   .\tests\browser\instance.ps1                      -> http://localhost:8095/index.html
#   .\tests\browser\instance.ps1 -Epc drogon.epc      -> that file open before the first paint
#   .\tests\browser\instance.ps1 -AppEnv FESPP_STEP_LOCAL=1   -> extra environment for the app
#   .\tests\browser\instance.ps1 -Stop                -> remove the container
#
# A container of its own rather than an instance already running: every page
# opened against the app leaves a pvpython session behind, so a run that
# throws its container away keeps the machine clean, and any other instance
# stays untouched on its own port.
#
# The three injections below are what makes the run test the WORKING TREE:
# the app package (imported from the venv's site-packages, NOT /deploy), the
# widget packages, and each widget's JS bundle under the name its module
# announces. A bundle missing from the static www is invisible to Python and
# only shows up in the browser as "trame_fespp_<x> is not defined".

param(
    [int]$Port = 8095,
    [string]$Name = "fespp_smoke",
    [string]$Image = "fespp_on_trame:local",
    # Optional: a file name of data\private to open at startup. Left out, the
    # app starts empty and the file is loaded through the Import data door.
    [string]$Epc = "",
    # Give the host's GPU to this instance. OFF by default ON PURPOSE: the
    # browser suite is about what the widgets DO, and a run that differs from
    # the one everybody else gets is a run that hides things. Use it to look
    # at a big grid by hand without waiting on software rendering.
    [switch]$Gpu,
    # Extra environment variables for the app, NAME=VALUE each (comma
    # separated for several), e.g. FESPP_STEP_LOCAL=1 for a probe that needs
    # a local file read in steps.
    [string[]]$AppEnv = @(),
    [switch]$Stop
)

# NOT "Stop": docker writing a line to stderr (removing a container that is not
# there) would raise a terminating NativeCommandError in PowerShell 5.1.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$site = "/deploy/server/venv/lib/python3.12/site-packages"
$www = "/deploy/server/www"

if ($Stop) {
    docker rm -f $Name 2>$null | Out-Null
    Write-Host "Container $Name removed." -ForegroundColor Yellow
    exit 0
}

docker rm -f $Name 2>$null | Out-Null

Write-Host "Starting $Name on port $Port..." -ForegroundColor Cyan
$dataDir = Join-Path $root "data\private"
$mount = @()
if (Test-Path $dataDir) { $mount = @("-v", "${dataDir}:/deploy/data/private:ro") }
# The strict mode is always on in a test instance (engine/strict.py): every
# exception of a bug type raised inside the app is written to the session log
# (/deploy/server/logs/launcher/<session>.txt), which test-browser.ps1 reads
# at the end of the run. FESPP_STRICT=all widens it, FESPP_STRICT=0 turns it off.
$strictMode = "1"
if ($env:FESPP_STRICT) { $strictMode = $env:FESPP_STRICT }
$gpuArgs = @()
if ($Gpu) {
    . (Join-Path $root "scripts\gpu-args.ps1")
    $gpuArgs = Get-FesppGpuArgs -Root $root
}
$envArgs = @()
foreach ($kv in $AppEnv) { $envArgs += @("-e", $kv) }
# the features not offered yet (app/core/previews) keep their coverage
docker run -d --name $Name -p "${Port}:80" -e "FESPP_STRICT=$strictMode" `
    -e "FESPP_ASSISTANT=1" -e "FESPP_VOLUMETRICS=1" -e "FESPP_RECONCILE=1" -e "FESPP_STRATIGRAPHY=1" `
    -e "FESPP_LOG_SAMPLE=1" @envArgs @mount @gpuArgs $Image | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker run failed" -ForegroundColor Red; exit 1 }

docker cp (Join-Path $root "fespp_on_trame") "${Name}:${site}/" | Out-Null
docker cp (Join-Path $root "fespp_on_trame\__main__.py") "${Name}:/deploy/fespp_on_trame/__main__.py" | Out-Null

$packages = @()
foreach ($w in Get-ChildItem (Join-Path $root "widgets") -Directory) {
    foreach ($p in Get-ChildItem $w.FullName -Directory -Filter "trame_*") {
        docker cp $p.FullName "${Name}:${site}/" | Out-Null
        $packages += $p.Name
        $serve = Join-Path $p.FullName "module\serve"
        $initFile = Join-Path $p.FullName "__init__.py"
        if (-not (Test-Path $serve)) { continue }
        if (-not (Test-Path $initFile)) { continue }
        $m = Select-String -Path $initFile -Pattern '__version__\s*=\s*"([^"]+)"'
        if (-not $m) { continue }
        $target = "$www/__$($p.Name)_$($m.Matches[0].Groups[1].Value)"
        docker exec $Name mkdir -p $target | Out-Null
        docker cp "$serve\." "${Name}:$target/" | Out-Null
    }
}
Write-Host "Injected: app + $($packages.Count) widget packages" -ForegroundColor Yellow

# apps.json lists what the image's www bake knew about. The app's own guard
# compares its enabled modules against that list and prints a warning for any
# that is missing; a widget added locally would trip it, so the list is
# realigned with what was just injected.
$modules = ($packages | ForEach-Object { "$_.module" }) -join ","
$py = @"
import json
p = "/opt/trame/apps.json"
d = json.load(open(p))
app = d.get("trame") or {}
mods = app.get("www_modules") or []
for m in "$modules".split(","):
    if m and m not in mods:
        mods.append(m)
app["www_modules"] = mods
d["trame"] = app
json.dump(d, open(p, "w"), indent=2)
"@
$py | docker exec -i $Name python3 - | Out-Null

if ($Epc) {
    # The launcher reads /deploy/server/launcher.json at EVERY container start
    # (run.sh copies it to /opt/trame/config.json), so this is the file to
    # rewrite: a patch of the copy is overwritten on the next start.
    $py = @"
import json
p = "/deploy/server/launcher.json"
d = json.load(open(p))
cmd = d["apps"]["trame"]["cmd"]
cmd[cmd.index("--local-epc-file-path") + 1] = "/deploy/data/private/$Epc"
json.dump(d, open(p, "w"), indent=2)
"@
    $py | docker exec -i $Name python3 - | Out-Null
    docker restart $Name | Out-Null
    Write-Host "Opens at startup: $Epc" -ForegroundColor Yellow
}

# Apache answers as soon as the container is up; the ParaView session itself
# is only started when a page is opened.
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/index.html" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ok) {
    Write-Host "[ERROR] no answer on http://localhost:$Port/index.html" -ForegroundColor Red
    docker logs --tail 40 $Name
    exit 1
}

Write-Host "Ready: http://localhost:$Port/index.html" -ForegroundColor Green
Write-Host "Logs : docker logs -f $Name" -ForegroundColor Gray
Write-Host "Stop : .\tests\browser\instance.ps1 -Stop -Name $Name" -ForegroundColor Gray
exit 0
