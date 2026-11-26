# Runs the application in a container on the given port, with the host's GPU
# when it is reachable.
#
#   .\run.ps1 8080:80                  -> fespp_on_trame:local (the build.ps1 image) on http://localhost:8080/
#   .\run.ps1 8080                     -> the same (the container port defaults to 80)
#   .\run.ps1 8080:80 -Image fespp_on_trame:pv6.1
#   .\run.ps1 8080:80 -NoGpu           -> software rendering (to compare a slowdown)
#   .\run.ps1 8080:80 -Stop            -> stop and remove this container
#
# The container is named fespp_<port> (fespp_8080): running the script again
# replaces the previous one without touching the others, and the name given
# by -Reserved is refused. The container does NOT restart by itself after a
# host reboot (-Restart for that).
param(
    [Parameter(Position = 0)]
    [string]$Ports = "8080:80",
    [string]$Image = "fespp_on_trame:local",
    [string]$Name = "",
    [switch]$NoGpu,
    [switch]$Restart,
    [switch]$Stop,
    # -Ia: the application joins the private network fespp_net and talks to
    # the local AI service (ia\run.ps1) at http://fespp_ia:8000; the
    # assistant then answers questions (RAG) and hands Mistral the requests
    # it cannot parse itself.
    [switch]$Ia,
    # A container name this script refuses, by default the name of the
    # deployed instance that may run on the same Docker host: starting a
    # container first removes any container of the same name, and -Stop
    # removes it outright, so either would take that instance down. ""
    # reserves no name.
    [string]$Reserved = "fespp",
    # Host folder of the Assistant's dialogue logs, one <Name> subfolder per
    # container. Empty: _local\assistant-logs in this tree.
    [string]$AssistantLogs = ""
)

# NOT "Stop": docker writes on STDERR, which PowerShell 5.1 turns into a
# terminating error under EAP=Stop. Failures are read from $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$parts = $Ports.Split(":")
$hostPort = $parts[0]
$ctrPort = if ($parts.Count -gt 1 -and $parts[1]) { $parts[1] } else { "80" }
if ($hostPort -notmatch '^\d+$' -or $ctrPort -notmatch '^\d+$') {
    Write-Host "[ERROR] ports expected as 8080:80 (or 8080), got: $Ports" -ForegroundColor Red
    exit 1
}
if (-not $Name) { $Name = "fespp_$hostPort" }
if ($Reserved -and $Name -eq $Reserved) {
    Write-Host "[ERROR] '$Name' is a reserved container name (-Reserved): this script never replaces or removes it. Choose another -Name." -ForegroundColor Red
    exit 1
}

if ($Stop) {
    docker rm -f $Name 2>$null | Out-Null
    Write-Host "Container $Name removed." -ForegroundColor Yellow
    exit 0
}

docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] image $Image not found: build it first (see README.md)." -ForegroundColor Red
    exit 1
}

# The host's GPU (see scripts\gpu-args.ps1): the helper returns an EMPTY
# array when none is available, and the container starts anyway, rendering
# in software.
$gpuArgs = @()
if (-not $NoGpu) {
    . (Join-Path $root "scripts\gpu-args.ps1")
    $gpuArgs = Get-FesppGpuArgs -Root $root
}
$restartArgs = if ($Restart) { @("--restart", "unless-stopped") } else { @() }
# The Assistant's dialogue log (fespp_on_trame/ia/journal.py) is written to a
# host folder: it outlives the container, and .\scripts\assistant-log.ps1
# reads it from the default folder. The path is made absolute, since docker
# takes a relative one for the name of a volume.
if (-not $AssistantLogs) { $AssistantLogs = Join-Path $root "_local\assistant-logs" }
$journal = (New-Item -ItemType Directory -Force (Join-Path $AssistantLogs $Name)).FullName
if (-not $journal) {
    Write-Host "[ERROR] cannot create the log folder under $AssistantLogs" -ForegroundColor Red
    exit 1
}
$logArgs = @("-v", "${journal}:/deploy/server/logs/assistant")
$iaArgs = @()
if ($Ia) {
    docker network inspect fespp_net *> $null
    if ($LASTEXITCODE -ne 0) { docker network create fespp_net | Out-Null }
    $iaArgs = @("--network", "fespp_net", "-e", "FESPP_IA_URL=http://fespp_ia:8000")
}

docker rm -f $Name 2>$null | Out-Null
# GPU options the host cannot honour make `docker run` fail: retry once
# without them.
docker run -d --name $Name @restartArgs -p "${hostPort}:${ctrPort}" @logArgs @iaArgs @gpuArgs $Image | Out-Null
if ($LASTEXITCODE -ne 0 -and $gpuArgs.Count) {
    Write-Host "[GPU] the start with the GPU failed: retrying with SOFTWARE rendering." -ForegroundColor Yellow
    docker rm -f $Name 2>$null | Out-Null
    docker run -d --name $Name @restartArgs -p "${hostPort}:${ctrPort}" @logArgs @iaArgs $Image | Out-Null
}
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker run ($Image) failed" -ForegroundColor Red; exit 1 }

# Wait up to 30 s for the page to answer, so the summary shows its status.
$code = ""
for ($i = 0; $i -lt 30; $i++) {
    $code = (curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:${hostPort}/")
    if ($code -eq "200") { break }
    Start-Sleep -Seconds 1
}
Write-Host ""
Write-Host "Container $Name ($Image) on http://localhost:${hostPort}/  (page: $code)" -ForegroundColor Green
if (-not $gpuArgs.Count) { Write-Host "SOFTWARE rendering (no GPU)." -ForegroundColor Yellow }
$stopCmd = ".\run.ps1 $Ports -Stop"
if ($Name -ne "fespp_$hostPort") { $stopCmd += " -Name $Name" }
Write-Host "Logs: docker logs -f $Name     Stop: $stopCmd" -ForegroundColor DarkGray
