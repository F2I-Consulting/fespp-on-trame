# Measure every chat model of ia\models on the two jobs of fespp_ia
# (questions through the RAG, and commands from a test set of user
# sentences), one model after the other: the service is restarted on each
# model and given up to 200 s to report "ok", the bench runs in the app
# image against it, and each model gets its report in ia\corpus_cache.
#
#   .\ia\bench-all.ps1                       -> every *.gguf of ia\models
#   .\ia\bench-all.ps1 -Models "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"
#   .\ia\bench-all.ps1 -Limit 20             -> 20 command sentences per model
#   .\ia\bench-all.ps1 -Commands mine.json   -> another command set, read from ia\corpus_cache
#   .\ia\bench-all.ps1 -AppImage fespp_on_trame:<tag>   -> the bench run in another build of the app image
param(
    [string[]]$Models = @(),
    [int]$Limit = 30,
    [string]$Commands = "",
    [string]$AppImage = "fespp_on_trame:local"
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $PSScriptRoot "corpus_cache"
if (-not $Models.Count) { $Models = Get-ChildItem (Join-Path $PSScriptRoot "models\*.gguf") | ForEach-Object { $_.Name } }
foreach ($m in $Models) {
    Write-Host "=== $m ===" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "run.ps1") -Model $m | Out-Null
    $ok = $false
    foreach ($i in 1..40) {
        Start-Sleep -Seconds 5
        try {
            $h = (Invoke-WebRequest -Uri http://127.0.0.1:8000/v1/health -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
            if ($h.status -eq "ok") { $ok = $true; break }
        } catch {}
    }
    if (-not $ok) { Write-Host "[bench] $m did not come up" -ForegroundColor Red; continue }
    $tag = ($m -replace "\.gguf$", "")
    $args_ = @("-m", "fespp_ia.bench", "--url", "http://host.docker.internal:8000", "--out", "/repo/ia/corpus_cache/bench-$tag.json",
               "--catalogue", "/repo/ia/corpus_cache/catalogue.json", "--limit", "$Limit")
    if ($Commands) { $args_ += @("--commands", "/repo/ia/corpus_cache/$Commands") }
    # host.docker.internal is the host where the service publishes its port;
    # Docker Desktop defines the name, Docker on Linux only with this mapping
    docker run --rm --add-host "host.docker.internal:host-gateway" -v "${root}:/repo" -w /repo/ia `
        --entrypoint /deploy/server/venv/bin/python $AppImage @args_
}
Write-Host "[bench] reports in $cache\bench-*.json" -ForegroundColor Green
