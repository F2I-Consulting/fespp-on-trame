# Visual regression tests for fespp-on-trame.
# Usage:
#   .\test-visual.ps1                       -> run every scenario, compare to baselines
#   .\test-visual.ps1 -Scenario eye_cycle   -> run one scenario
#   .\test-visual.ps1 -UpdateBaselines      -> re-record the expected screenshots
#   .\test-visual.ps1 -Gpu                  -> add --gpus all (default: software rendering,
#                                              same as the normally-launched containers)
#
# Each scenario boots a throwaway container of $Image with the app in
# headless scenario mode (FESPP_SCENARIO env -> core/engine/scenario.py),
# mounts data\private as /tmp/testdata (read-only), collects the
# screenshots and diffs them against tests\visual\baselines\<scenario>\
# (local, gitignored — they depend on this machine's GPU rendering).

param(
    [string]$Scenario = "all",
    [switch]$UpdateBaselines,
    [switch]$Gpu,
    [string]$Image = "fespp_on_trame:local",
    # Optional: inject a LOCAL fespp_on_trame source tree over the image's
    # /deploy copy before the run — validates a fix without rebuilding the
    # image (same loop as a hot-deploy).
    [string]$App = ""
)

# NOT "Stop": with EAP=Stop, any native command whose redirected stderr
# emits a line (docker exec on a dead container, docker rm on a missing
# one) raises a terminating NativeCommandError in PowerShell 5.1.
# Failures are handled explicitly through exit codes below.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$visDir = Join-Path $root "tests\visual"
$scDir = Join-Path $visDir "scenarios"
$blDir = Join-Path $visDir "baselines"
$outDir = Join-Path $visDir "out"
$dataDir = Join-Path $root "data\private"

$scenarios = Get-ChildItem $scDir -Filter *.json
if ($Scenario -ne "all") {
    $scenarios = $scenarios | Where-Object { $_.BaseName -eq $Scenario }
    if (-not $scenarios) { Write-Host "Unknown scenario: $Scenario" -ForegroundColor Red; exit 1 }
}

$anyFail = $false
foreach ($sc in $scenarios) {
    $name = $sc.BaseName
    Write-Host ""
    Write-Host "=== scenario: $name ===" -ForegroundColor Cyan
    $cname = "fespp_vis_$name"
    try { docker rm -f $cname 2>$null | Out-Null } catch {}

    $gpuArgs = @()
    if ($Gpu) { $gpuArgs = @("--gpus", "all") }
    docker create --name $cname @gpuArgs `
        -e FESPP_SCENARIO=/tmp/scenario.json `
        -e FESPP_SCENARIO_OUT=/tmp/visual_out `
        -v "${dataDir}:/tmp/testdata:ro" `
        --entrypoint /opt/paraview/bin/pvpython $Image `
        /deploy/fespp_on_trame --server --host 127.0.0.1 --port 9600 `
        --fespp-plugin-path /work/ttl/install-fespp/lib/paraview-6.0/plugins/Fespp/Fespp.so `
        --local-epc-file-path /deploy/data/empty.epc | Out-Null
    docker cp "$($sc.FullName)" "${cname}:/tmp/scenario.json" | Out-Null
    if ($App) {
        # /deploy n'est que le shim __main__ : les imports du paquet
        # resolvent depuis le site-packages du venv (PV_VENV) — injecter
        # aux DEUX emplacements, sinon le code local est inerte.
        docker cp "$App" "${cname}:/deploy/" | Out-Null
        docker cp "$App" "${cname}:/deploy/server/venv/lib/python3.12/site-packages/" | Out-Null
    }
    docker start $cname | Out-Null

    # Poll for the DONE marker (the scenario runner always writes it).
    $deadline = (Get-Date).AddMinutes(10)
    $done = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        docker exec $cname test -f /tmp/visual_out/DONE 2>$null
        if ($LASTEXITCODE -eq 0) { $done = $true; break }
        $running = docker inspect -f "{{.State.Running}}" $cname
        if ($running -ne "true") { break }
    }

    $scOut = Join-Path $outDir $name
    if (Test-Path $scOut) { Remove-Item -Recurse -Force $scOut }
    New-Item -ItemType Directory -Force $scOut | Out-Null
    try { docker cp "${cname}:/tmp/visual_out/." $scOut | Out-Null } catch {}
    # Keep the app's stdout/stderr — the scenario runner's [SCENARIO]
    # lines and any engine error land there, not in scenario.log.
    docker logs $cname > (Join-Path $scOut "app.log") 2>&1
    docker rm -f $cname | Out-Null

    if (-not $done) {
        Write-Host "[$name] TIMEOUT or app crash (see $scOut\scenario.log)" -ForegroundColor Red
        $anyFail = $true
        continue
    }
    if (Test-Path (Join-Path $scOut "ERROR.txt")) {
        Write-Host "[$name] SCENARIO ERROR: $(Get-Content (Join-Path $scOut 'ERROR.txt'))" -ForegroundColor Red
        $anyFail = $true
        continue
    }

    if ($UpdateBaselines) {
        $scBl = Join-Path $blDir $name
        if (Test-Path $scBl) { Remove-Item -Recurse -Force $scBl }
        New-Item -ItemType Directory -Force $scBl | Out-Null
        Copy-Item (Join-Path $scOut "*.png") $scBl
        Write-Host "[$name] baselines updated ($((Get-ChildItem $scBl -Filter *.png).Count) images)" -ForegroundColor Yellow
    } else {
        $scBl = Join-Path $blDir $name
        if (-not (Test-Path $scBl)) {
            Write-Host "[$name] no baselines — run .\test-visual.ps1 -UpdateBaselines first" -ForegroundColor Red
            $anyFail = $true
            continue
        }
        docker run --rm `
            -v "${scBl}:/b:ro" -v "${scOut}:/c" `
            -v "${visDir}\compare.py:/compare.py:ro" `
            --entrypoint /opt/paraview/bin/pvpython $Image /compare.py /b /c
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[$name] VISUAL DIFF — see ${scOut}\*_diff.png" -ForegroundColor Red
            $anyFail = $true
        } else {
            Write-Host "[$name] PASS" -ForegroundColor Green
        }
    }
}

Write-Host ""
if ($anyFail) { Write-Host "VISUAL TESTS: FAIL" -ForegroundColor Red; exit 1 }
if ($UpdateBaselines) { Write-Host "BASELINES RECORDED" -ForegroundColor Yellow; exit 0 }
Write-Host "VISUAL TESTS: PASS" -ForegroundColor Green
exit 0
