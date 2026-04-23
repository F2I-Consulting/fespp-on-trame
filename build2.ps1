# Build script for fespp-on-trame Docker image
# Usage:
#   .\build.ps1                                    -> Build from GitHub (tag: dev)
#   .\build.ps1 E:\Dev\fespp\work\src              -> Build from local source (tag: local)

param(
    [string]$SourcePath = ""
)

$ErrorActionPreference = "Stop"
$LocalSrcDir = "fespp-src-local"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FESPP-ON-TRAME Docker Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Clean up existing fespp-src-local directory
if (Test-Path $LocalSrcDir) {
    Write-Host "Cleaning up existing $LocalSrcDir..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $LocalSrcDir
}

if ($SourcePath -ne "") {
    # LOCAL MODE: Copy source and build with 'local' tag
    Write-Host "MODE: LOCAL (from $SourcePath)" -ForegroundColor Green
    Write-Host ""

    if (-not (Test-Path $SourcePath)) {
        Write-Host "[ERROR] Source path does not exist: $SourcePath" -ForegroundColor Red
        exit 1
    }

    if (-not (Test-Path "$SourcePath\CMakeLists.txt")) {
        Write-Host "[ERROR] CMakeLists.txt not found in: $SourcePath" -ForegroundColor Red
        Write-Host "Make sure you're pointing to the FESPP source root directory." -ForegroundColor Red
        exit 1
    }

    Write-Host "Copying FESPP source from $SourcePath to $LocalSrcDir..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $LocalSrcDir -Force | Out-Null
    Copy-Item -Path "$SourcePath\*" -Destination $LocalSrcDir -Recurse -Force
    Write-Host "[OK] Source copied" -ForegroundColor Green
    Write-Host ""

    Write-Host "Building Docker image with tag 'fespp_on_trame:local'..." -ForegroundColor Yellow
    docker build -f Dockerfile -t fespp_on_trame:local2 .

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Docker build failed!" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Image: fespp_on_trame:local" -ForegroundColor Green
    Write-Host "Source: LOCAL ($SourcePath)" -ForegroundColor Green

} else {
    # GITHUB MODE: No source copy, build with 'dev' tag
    Write-Host "MODE: GITHUB (from https://github.com/F2I-Consulting/fespp)" -ForegroundColor Green
    Write-Host ""

    Write-Host "Building Docker image with tag 'fespp_on_trame:dev'..." -ForegroundColor Yellow
    docker build -f Dockerfile -t fespp_on_trame:dev .

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Docker build failed!" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Image: fespp_on_trame:dev" -ForegroundColor Green
    Write-Host "Source: GITHUB (dev branch)" -ForegroundColor Green
}

Write-Host ""
