# Run fespp_ia with the models of ia\models.
#   .\ia\run.ps1                          -> fespp_ia:cpu on 127.0.0.1:8000, with the chat model compose.yaml
#                                            names (Ministral-3-3B-Instruct-2512-Q4_K_M.gguf) when ia\models
#                                            holds it, else the only .gguf there
#   .\ia\run.ps1 -Cuda                    -> fespp_ia:cuda, --gpus all
#   .\ia\run.ps1 -Model Ministral-3-8B-Instruct-2512-Q4_K_M.gguf   -> another model of ia\models
#   .\ia\run.ps1 -Index index-dev         -> another index of ia\models than index: the developer's
#                                            (.\ia\build-index.ps1 -Developer)
#   .\ia\run.ps1 -Stop
# The port is published on 127.0.0.1 ONLY: the service is never reached from
# the network. Next to the app of .\run.ps1 -Ia, both join the private
# network `fespp_net` and the app speaks to http://fespp_ia:8000. The
# container restarts with Docker (--restart unless-stopped); -Stop removes it.
param([switch]$Cuda, [string]$Model = "", [int]$Port = 8000, [string]$Index = "", [switch]$Stop)

$ErrorActionPreference = "Continue"
$name = "fespp_ia"
# an index that is not there is said before the running service is removed
if ($Index -and -not (Test-Path -PathType Container (Join-Path $PSScriptRoot "models\$Index"))) {
    Write-Host "[ERROR] no index ia\models\$Index" -ForegroundColor Red; exit 1
}
docker rm -f $name 2>$null | Out-Null
if ($Stop) { Write-Host "[OK] $name stopped"; exit 0 }

docker network inspect fespp_net *> $null
if ($LASTEXITCODE -ne 0) { docker network create fespp_net | Out-Null }

$models = Join-Path $PSScriptRoot "models"
# the default model named rather than guessed: with several .gguf in the
# folder and none named, the service loads none
$default = "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"
if (-not $Model -and (Test-Path (Join-Path $models $default))) { $Model = $default }
$image = if ($Cuda) { "fespp_ia:cuda" } else { "fespp_ia:cpu" }
$args_ = @("run", "-d", "--name", $name, "--restart", "unless-stopped", "--network", "fespp_net",
           "-p", "127.0.0.1:${Port}:8000", "-v", "${models}:/models:ro")
if ($Cuda) { $args_ += @("--gpus", "all") }
if ($Model) { $args_ += @("-e", "FESPP_IA_CHAT_MODEL=$Model") }
if ($Index) { $args_ += @("-e", "FESPP_IA_INDEX=/models/$Index") }
$args_ += $image
docker @args_
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker run failed" -ForegroundColor Red; exit 1 }
Write-Host "[OK] $name ($image$(if ($Model) { ", $Model" })) on http://127.0.0.1:$Port/v1/health" -ForegroundColor Green
