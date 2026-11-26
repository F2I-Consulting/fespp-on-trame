# Build one self-contained fespp_ia image per chat model of ia\models
# (ia\Dockerfile.model): fespp_ia:ministral-3b, fespp_ia:mistral-7b, ...
#   .\ia\build-models.ps1                 -> every *.gguf of ia\models
#   .\ia\build-models.ps1 -Models "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
#   .\ia\build-models.ps1 -Cuda           -> from fespp_ia:cuda (tags suffixed -cuda)
# The build context is ia\models, cut down to the ONE model being baked (a
# .dockerignore written for the build and removed after it): without it,
# Docker sends every model of the folder (tens of GB) on each build.
# A model without an entry in $tags is tagged after its lower-cased file name.
param([string[]]$Models = @(), [switch]$Cuda)
$ErrorActionPreference = "Continue"   # docker writes its progress on STDERR
$modelDir = Join-Path $PSScriptRoot "models"
$tags = @{
    "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"                  = "ministral-3b"
    "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"                  = "ministral-8b"
    "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf"                      = "mistral-7b"
    "Mistral-Nemo-Instruct-2407-Q4_K_M.gguf"                    = "nemo-12b"
    "mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf" = "mistral-small-24b"
}
if (-not $Models.Count) { $Models = Get-ChildItem (Join-Path $modelDir "*.gguf") | ForEach-Object { $_.Name } }
$base = if ($Cuda) { "fespp_ia:cuda" } else { "fespp_ia:cpu" }
$ignore = Join-Path $modelDir ".dockerignore"
foreach ($m in $Models) {
    $tag = $tags[$m]
    if (-not $tag) { $tag = (($m -replace "\.gguf$", "").ToLower() -replace "[^a-z0-9_.-]", "-") }
    if ($Cuda) { $tag += "-cuda" }
    Write-Host "=== fespp_ia:$tag  <- $m" -ForegroundColor Cyan
    Set-Content -Path $ignore -Value @("*.gguf", "*.part", "!$m") -Encoding ascii
    docker build -f (Join-Path $PSScriptRoot "Dockerfile.model") --build-arg BASE=$base --build-arg MODEL=$m -t "fespp_ia:$tag" $modelDir
    $rc = $LASTEXITCODE
    Remove-Item -ErrorAction SilentlyContinue $ignore
    if ($rc -ne 0) { Write-Host "[ERROR] fespp_ia:$tag" -ForegroundColor Red } else { Write-Host "[OK] fespp_ia:$tag" -ForegroundColor Green }
}
docker images --format "{{.Repository}}:{{.Tag}}  {{.Size}}" | Select-String "^fespp_ia:"
