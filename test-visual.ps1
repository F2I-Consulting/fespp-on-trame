# Visual regression tests for fespp-on-trame.
# Usage:
#   .\test-visual.ps1                       -> run every scenario, compare to baselines
#   .\test-visual.ps1 -Scenario eye_cycle   -> run one scenario
#   .\test-visual.ps1 -UpdateBaselines      -> re-record the expected screenshots
#   .\test-visual.ps1 -Software             -> render on the processor instead of the GPU
#
# The scenes are drawn by the host's graphics card by default: the baselines
# are recorded that way since 17/10/2026 (software rendering timed calc_diff
# and well_layout out, and another rasteriser draws other pixels, so a
# software run can only measure, never compare). -Gpu is still accepted.
# Inject the working tree to test the code of the repository, not the image's
# copy: -App (Resolve-Path .\fespp_on_trame).Path -Widgets
#
# Each scenario boots a throwaway container of $Image with the app in
# headless scenario mode (FESPP_SCENARIO env ->
# tests/visual/runner/scenario.py, injected below), mounts data\private as /tmp/testdata
# (read-only), collects the screenshots and diffs them against
# tests\visual\baselines\<scenario>\ (local and gitignored: the pixels
# depend on the machine that recorded them). A scenario that takes no
# screenshot passes on its own checks, with or without a baselines folder.

param(
    [string]$Scenario = "all",
    [switch]$UpdateBaselines,
    [switch]$Gpu,
    [switch]$Software,
    [string]$Image = "fespp_on_trame:local",
    # Optional: inject a LOCAL fespp_on_trame source tree over the image's
    # copy before the run, to validate a change without rebuilding the image.
    [string]$App = "",
    # Optional: inject the LOCAL widget packages (widgets/*/trame_*) into the
    # image's venv too, to test a new or changed widget without rebuilding
    # the image (the Dockerfile copies the same directories at build time).
    [switch]$Widgets,
    # The memory a scenario's container may take, swap included: past it the
    # kernel kills the app there (container_state.txt says oom=true) instead
    # of starving every other container of the machine, the public server
    # among them.
    [string]$Memory = "8g"
)

# NOT "Stop": with EAP=Stop, any native command whose redirected stderr
# emits a line (docker exec on a dead container, docker rm on a missing
# one) raises a terminating NativeCommandError in PowerShell 5.1.
# Failures are handled explicitly through exit codes below.
# ASCII only, string literals above all: this file has no BOM, so
# PowerShell 5.1 reads it in the ANSI code page, where the bytes of an em
# dash include a typographic quote that closes the string; the compare block
# below then silently becomes an untaken branch and every run reports PASS.
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

# The FESPP plugin of THIS image: images built on ParaView 6.1 or later have
# the stable link lib/paraview (build-fespp.sh), older ones only
# lib/paraview-<version>. Both are searched, so this harness can still
# replay an older image.
$plugin = (docker run --rm --entrypoint sh $Image -c "ls -d /work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so /work/ttl/install-fespp/lib/paraview-*/plugins/Fespp/Fespp.so 2>/dev/null | head -1" | Out-String).Trim()
if (-not $plugin) {
    Write-Host "[ERROR] no Fespp.so under /work/ttl/install-fespp/lib in $Image" -ForegroundColor Red
    exit 1
}
Write-Host "FESPP plugin in ${Image}: $plugin" -ForegroundColor DarkGray

$anyFail = $false
foreach ($sc in $scenarios) {
    $name = $sc.BaseName
    Write-Host ""
    Write-Host "=== scenario: $name ===" -ForegroundColor Cyan
    $cname = "fespp_vis_$name"
    try { docker rm -f $cname 2>$null | Out-Null } catch {}

    # The host's graphics card draws the scenes (the baselines are recorded
    # that way); -Software draws on the processor, to measure only: another
    # rasteriser draws other pixels.
    $gpuArgs = @()
    if (-not $Software) {
        . (Join-Path $root "scripts\gpu-args.ps1")
        $gpuArgs = Get-FesppGpuArgs -Root $root
    }
    # The strict mode is ALWAYS on (fespp_on_trame/engine/strict.py): every
    # exception of a bug type raised inside the app during the run is listed
    # in app.log and fails the scenario below, swallowed or not.
    # FESPP_STRICT=all on the host widens it to every exception,
    # FESPP_STRICT=0 switches it off.
    $strictMode = "1"
    if ($env:FESPP_STRICT) { $strictMode = $env:FESPP_STRICT }
    # the features not offered yet (app/core/previews) keep their coverage
    $strictArgs = @("-e", "FESPP_STRICT=$strictMode", "-e", "FESPP_ASSISTANT=1",
                    "-e", "FESPP_VOLUMETRICS=1",
                    "-e", "FESPP_RECONCILE=1", "-e", "FESPP_STRATIGRAPHY=1",
                    "-e", "FESPP_LOG_SAMPLE=1")
    # an OSDU token set on the host reaches the container's environment
    # (the etp_* ops of the driver), by name: its value is in no file, no log
    $tokenArgs = @()
    if ($env:OSDU_TOKEN) { $tokenArgs = @("-e", "OSDU_TOKEN") }
    # --timeout 0: trame (wslink) otherwise stops the server, exit 0, after
    # 300 s without a client, and the scenario runner is no client: every
    # scenario longer than five minutes died at the five-minute mark, logs
    # cut short, no stack (29/10). A comment cannot sit inside the
    # backtick-continued command below: it ends it.
    docker create --name $cname @gpuArgs @strictArgs @tokenArgs `
        --memory $Memory --memory-swap $Memory `
        -e FESPP_SCENARIO=/tmp/scenario.json `
        -e FESPP_SCENARIO_RUNNER=/tmp/runner/scenario.py `
        -e FESPP_SCENARIO_OUT=/tmp/visual_out `
        -v "${dataDir}:/tmp/testdata:ro" `
        --entrypoint /opt/paraview/bin/pvpython $Image `
        /deploy/fespp_on_trame --server --host 127.0.0.1 --port 9600 --timeout 0 `
        --fespp-plugin-path $plugin `
        --local-epc-file-path /deploy/data/empty.epc | Out-Null
    docker cp "$($sc.FullName)" "${cname}:/tmp/scenario.json" | Out-Null
    # the scenario driver lives with the tests, not in the product (Q9)
    docker cp (Join-Path $root "tests\visual\runner") "${cname}:/tmp/runner" | Out-Null
    if ($App) {
        # The /deploy copy only serves as the __main__ entry point: package
        # imports resolve from the venv's site-packages (PV_VENV), so the
        # tree is copied to BOTH places, or the local code is never imported.
        docker cp "$App" "${cname}:/deploy/" | Out-Null
        docker cp "$App" "${cname}:/deploy/server/venv/lib/python3.12/site-packages/" | Out-Null
    }
    if ($Widgets) {
        foreach ($w in Get-ChildItem (Join-Path $root "widgets") -Directory) {
            foreach ($p in Get-ChildItem $w.FullName -Directory -Filter "trame_*") {
                docker cp $p.FullName "${cname}:/deploy/server/venv/lib/python3.12/site-packages/" | Out-Null
            }
        }
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
    # Keep the app's stdout/stderr: the scenario runner's [SCENARIO] lines
    # and any engine error land there, not in scenario.log.
    docker logs $cname > (Join-Path $scOut "app.log") 2>&1
    # How the container ended: a process the kernel killed (out of memory)
    # or that left through exit() writes no Python stack, only this.
    $cstate = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} err={{.State.Error}} finished={{.State.FinishedAt}}" $cname
    Set-Content -Path (Join-Path $scOut "container_state.txt") -Value $cstate -Encoding ascii
    Write-Host "[$name] container: $cstate"
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
    # An exception of a bug type raised inside the app is a failure even when
    # a handler swallowed it: the strict reporter prints one line per site
    # ("[fespp-strict] NameError: ...  (engine/x.py:12, in f)"); its own
    # status lines ("armed", "no exception", the summary) are not sites.
    $strictSites = @(Get-Content (Join-Path $scOut "app.log") | Select-String -Pattern "^\[fespp-strict\] [A-Za-z]+Error: |^\[fespp-strict\] [A-Za-z]+Exception: |^\[fespp-strict\] AssertionError")
    if ($strictSites.Count -gt 0) {
        Write-Host "[$name] STRICT: $($strictSites.Count) exception site(s) raised inside the app (see $scOut\app.log)" -ForegroundColor Red
        foreach ($line in $strictSites | Select-Object -First 8) { Write-Host "    $($line.Line)" -ForegroundColor Red }
        $anyFail = $true
        continue
    }
    # A gesture the app refused ("gesture refused: {...}") is a scenario that
    # no longer speaks the app's language: what it meant to check is not checked.
    $refused = @(Get-Content (Join-Path $scOut "app.log") | Select-String -SimpleMatch "gesture refused: ")
    if ($refused.Count -gt 0) {
        Write-Host "[$name] FAIL: $($refused.Count) gesture(s) of the scenario refused by the app (see $scOut\app.log)" -ForegroundColor Red
        foreach ($line in $refused | Select-Object -First 4) { Write-Host "    $($line.Line)" -ForegroundColor Red }
        $anyFail = $true
        continue
    }
    # A scenario on a live ETP server stops at its etp_open without a token
    # (the suite runs without a server): it checked nothing, so it does not
    # say PASS.
    $logFile = Join-Path $scOut "scenario.log"
    if ((Test-Path $logFile) -and @(Get-Content $logFile | Select-String -SimpleMatch "etp_open: no OSDU_TOKEN").Count -gt 0) {
        Write-Host "[$name] NOT RUN: no OSDU_TOKEN in the environment, the steps after etp_open were skipped" -ForegroundColor Yellow
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
        # A scenario made of probes alone (no shot) has no pixels to compare:
        # its own checks decided above, and it passes here. Tested before the
        # baselines folder, which is local: a fresh clone has none at all.
        $shots = @(Get-ChildItem $scOut -Filter *.png)
        $refs = @()
        if (Test-Path $scBl) { $refs = @(Get-ChildItem $scBl -Filter *.png) }
        if ($shots.Count -eq 0 -and $refs.Count -eq 0) {
            Write-Host "[$name] PASS (probes only, no screenshot)" -ForegroundColor Green
            continue
        }
        if (-not (Test-Path $scBl)) {
            Write-Host "[$name] no baselines - run .\test-visual.ps1 -UpdateBaselines first" -ForegroundColor Red
            $anyFail = $true
            continue
        }
        docker run --rm `
            -v "${scBl}:/b:ro" -v "${scOut}:/c" `
            -v "${visDir}\compare.py:/compare.py:ro" `
            --entrypoint /opt/paraview/bin/pvpython $Image /compare.py /b /c
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[$name] VISUAL DIFF - see ${scOut}\*_diff.png" -ForegroundColor Red
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
