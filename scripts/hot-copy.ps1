# Copy the working tree's app and widgets into a RUNNING container, hot,
# with no restart: every page opened afterwards is a new pvpython session
# that imports the new code (pages already open keep the old code until
# reloaded).
#
#   .\scripts\hot-copy.ps1                     -> fespp_8080
#   .\scripts\hot-copy.ps1 -Name fespp_8095
#   .\scripts\hot-copy.ps1 -Rollback           -> puts back the last backup
#
# The same injection as tests/browser/instance.ps1, on a container that is
# already serving. Before copying, the container's current app and widget
# packages are kept in /tmp/hot-backup-<stamp>-<sha> (and named in
# /tmp/hot-backup-last), so -Rollback can put them back. -Rollback restores
# the Python packages and __main__.py only: the widget bundles under www
# and the apps.json entries stay as copied.
#
# It REFUSES the container named by -Reserved ("fespp" by default), the
# deployed instance: a hot copy would hand its users the working tree's code
# from the next page they open, and that one is only ever updated by hand,
# in an agreed maintenance window. -Reserved "" reserves no name.
param([string]$Name = "fespp_8080", [switch]$Rollback, [string]$Reserved = "fespp")

$ErrorActionPreference = "Continue"
if ($Reserved -and $Name -eq $Reserved) {
    Write-Host "[REFUSED] '$Name' is the reserved container (-Reserved): it is only ever updated by hand, never by a hot copy." -ForegroundColor Red
    exit 1
}
$running = docker ps --filter "name=^/${Name}$" --format "{{.Names}}"
if ($running -ne $Name) { Write-Host "[ERROR] container $Name is not running" -ForegroundColor Red; exit 1 }

$root = Split-Path $PSScriptRoot -Parent
$site = "/deploy/server/venv/lib/python3.12/site-packages"
$www = "/deploy/server/www"

if ($Rollback) {
    $last = (docker exec $Name sh -c "cat /tmp/hot-backup-last 2>/dev/null").Trim()
    if (-not $last) { Write-Host "[ERROR] no backup recorded in $Name" -ForegroundColor Red; exit 1 }
    docker exec $Name sh -c "cp -r $last/site/. $site/ && cp $last/__main__.py /deploy/fespp_on_trame/__main__.py" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] rollback failed" -ForegroundColor Red; exit 1 }
    Write-Host "[OK] $Name rolled back to $last (reload the pages)" -ForegroundColor Green
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sha = (git -C $root rev-parse --short HEAD 2>$null)
$backup = "/tmp/hot-backup-$stamp-$sha"
docker exec $Name sh -c "mkdir -p $backup/site && cp -r $site/fespp_on_trame $site/trame_fespp_* $backup/site/ && cp /deploy/fespp_on_trame/__main__.py $backup/ && echo $backup > /tmp/hot-backup-last" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] backup failed, nothing copied" -ForegroundColor Red; exit 1 }

docker cp (Join-Path $root "fespp_on_trame") "${Name}:${site}/" | Out-Null
docker cp (Join-Path $root "fespp_on_trame\__main__.py") "${Name}:/deploy/fespp_on_trame/__main__.py" | Out-Null
$packages = @()
foreach ($w in Get-ChildItem (Join-Path $root "widgets") -Directory) {
    foreach ($p in Get-ChildItem $w.FullName -Directory -Filter "trame_*") {
        docker cp $p.FullName "${Name}:${site}/" | Out-Null
        $packages += $p.Name
        $serve = Join-Path $p.FullName "module\serve"
        $initFile = Join-Path $p.FullName "__init__.py"
        if (-not (Test-Path $serve) -or -not (Test-Path $initFile)) { continue }
        $m = Select-String -Path $initFile -Pattern '__version__\s*=\s*"([^"]+)"'
        if (-not $m) { continue }
        $target = "$www/__$($p.Name)_$($m.Matches[0].Groups[1].Value)"
        docker exec $Name mkdir -p $target | Out-Null
        docker cp "$serve\." "${Name}:$target/" | Out-Null
    }
}
# drop the copied packages' bytecode: the newer sources win anyway, this
# only clears compiled leftovers
docker exec $Name sh -c "find $site/fespp_on_trame $site/trame_fespp_* -name '*.pyc' -delete" | Out-Null

# the app's bundle guard checks its widget modules against apps.json:
# register every copied widget package there that is not listed yet
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
Write-Host "[OK] $Name <- app ($sha + working tree) + $($packages.Count) widget packages; backup $backup. Reload the pages." -ForegroundColor Green
