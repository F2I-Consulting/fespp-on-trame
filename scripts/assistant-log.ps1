# Fetch the assistant's dialogue journal from an app container and report
# what it shows needs work (scripts/assistant_log_report.py, run in the image).
#
#   .\scripts\assistant-log.ps1 <container>
#   .\scripts\assistant-log.ps1 <container> -Image fespp_on_trame:<tag>   -> the report run in another build of the app image
#
# The container is always named, never guessed: without a name, the script
# lists the running containers and stops. run.ps1 names its containers
# fespp_<port> (fespp_8080 for port 8080); docker compose names the app
# <project>-app-1 (docker compose ps shows it).
#
# A container that writes its journal into a host folder (run.ps1 and
# compose.yaml mount one) is read there, in place; the journal of any other
# container is copied into _local\assistant-logs\<container>\ (never
# committed). The sentences worth reviewing land next to the journal, in
# candidates.jsonl.
param([Parameter(Position = 0)][string]$Name = "", [string]$Image = "fespp_on_trame:local")

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
if (-not $Name) {
    Write-Host "[ERROR] name the app container: .\scripts\assistant-log.ps1 <container>" -ForegroundColor Red
    Write-Host "Running containers:"
    docker ps --format "  {{.Names}}  ({{.Image}})"
    exit 1
}
$json = docker inspect $Name --format "{{json .Mounts}}" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] no container named $Name" -ForegroundColor Red; exit 1 }
$mounts = $json | ConvertFrom-Json
$bound = $mounts | Where-Object { $_.Type -eq "bind" -and $_.Destination -eq "/deploy/server/logs/assistant" } |
    Select-Object -First 1
if ($bound) {
    # the journal is already on the host: read it where it is, since copying
    # it onto itself would truncate it (the folder named after the container
    # is the one run.ps1 mounts, when docker reports a path this shell cannot reach)
    $dest = if (Test-Path -PathType Container $bound.Source) { $bound.Source } else { Join-Path $root "_local\assistant-logs\$Name" }
} else {
    $dest = Join-Path $root "_local\assistant-logs\$Name"
    New-Item -ItemType Directory -Force $dest | Out-Null
    docker cp "${Name}:/deploy/server/logs/assistant/." "$dest" 2>$null | Out-Null
}
if (-not (Get-ChildItem $dest -Filter "assistant-*.jsonl" -ErrorAction SilentlyContinue)) {
    Write-Host "[INFO] no journal yet in $Name (nothing typed in the Assistant since the copy?)" -ForegroundColor Yellow
    exit 0
}
docker run --rm -v "${root}:/repo:ro" -v "${dest}:/logs" --entrypoint /deploy/server/venv/bin/python `
    $Image /repo/scripts/assistant_log_report.py /logs --candidates /logs/candidates.jsonl
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] the report failed in $Image" -ForegroundColor Red; exit 1 }
# the report names the folder as the container sees it (/logs)
Write-Host "[OK] journal and candidates.jsonl in $dest" -ForegroundColor Green
