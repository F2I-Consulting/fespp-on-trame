# Build the fespp_ia image.
#   .\ia\build.ps1            -> fespp_ia:cpu   (any machine, no CUDA)
#   .\ia\build.ps1 -Cuda      -> fespp_ia:cuda  (NVIDIA GPU, every layer offloaded)
param([switch]$Cuda)

$ErrorActionPreference = "Continue"   # docker writes its progress on STDERR
$here = $PSScriptRoot
if ($Cuda) {
    docker build -t fespp_ia:cuda $here `
        --build-arg LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda `
        --build-arg GPU_LAYERS=99
} else {
    docker build -t fespp_ia:cpu $here
}
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] build failed" -ForegroundColor Red; exit 1 }
Write-Host "[OK] fespp_ia:$(if ($Cuda) {'cuda'} else {'cpu'})" -ForegroundColor Green
