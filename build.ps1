# Build script for fespp-on-trame Docker image
# Usage:
#   .\build.ps1                                       -> Build from GitHub (tag: dev)
#   .\build.ps1 <path-to-fespp-sources>               -> Build from local source (tag: local)
#   .\build.ps1 <path-to-fespp-sources> -Tag pv6.1    -> same, into fespp_on_trame:pv6.1
#   .\build.ps1 ... -FetpapiRef 169ec04               -> fetpapi at that tag or sha (build argument)
#   .\build.ps1 ... -BuildJobs 6                       -> six parallel compilations instead of every core
#     (a candidate built next to the validated `local`, which every harness
#     and run.ps1 use by default, instead of over it; -Tag names the image
#     in either mode)
#
# <path-to-fespp-sources> is the root of a FESPP checkout (the folder that
# holds its CMakeLists.txt). Every path is taken from this script's own
# folder, whatever the current directory: the sources are copied into
# fespp-src-local\ there (the Docker build context, which the Dockerfile
# reads with `COPY fespp-src-local*`), and that copy is REMOVED once the
# build has ended, success or failure: left behind, a later `docker build`
# run by hand would compile these sources instead of the GitHub ref.
# The toolchain image paraview:6.0.x must exist first (README.md, step 1).

param(
    [string]$SourcePath = "",
    [string]$Tag = "",
    # fetpapi release tag or commit sha to build (FETPAPI_GIT_TAG build argument,
    # Dockerfile); the Dockerfile default when empty
    [string]$FetpapiRef = "",
    # compile parallelism of fesapi, fetpapi and FESPP (FESPP_BUILD_JOBS build
    # argument); 0 = every core. 6 keeps the Docker engine responsive on a PC
    # that also runs the app containers
    [int]$BuildJobs = 0
)

# Build arguments common to every docker build below
$buildArgs = @()
if ($FetpapiRef) { $buildArgs += @("--build-arg", "FETPAPI_GIT_TAG=$FetpapiRef") }
if ($BuildJobs -gt 0) { $buildArgs += @("--build-arg", "FESPP_BUILD_JOBS=$BuildJobs") }

# NOT "Stop": docker writes its build progress on STDERR, and in PowerShell
# 5.1 a native command writing there under EAP=Stop raises a terminating
# NativeCommandError, which would end the script on the first progress line
# while the build carries on in the daemon. Failures are read from
# $LASTEXITCODE instead, which is what says whether docker succeeded, as in
# test-visual.ps1, instance.ps1 and run.ps1.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$LocalSrcDir = Join-Path $Root "fespp-src-local"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FESPP-ON-TRAME Docker Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Remove-LocalSources {
    if (Test-Path $LocalSrcDir) {
        Write-Host "Removing $LocalSrcDir..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $LocalSrcDir
    }
}

# A copy left by an earlier run must never reach a GitHub build
Remove-LocalSources

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

    $t = if ($Tag) { $Tag } else { "local" }
    try {
        # ParaView + fesapi/fetpapi first, as a build of their own: a build that
        # fails keeps none of its long steps in BuildKit's cache, so a FESPP
        # compile error would otherwise cost the whole ParaView superbuild again.
        # Seconds when cached; the tag doubles as a dev image to compile FESPP
        # against by hand.
        Write-Host "Building ParaView + fesapi/fetpapi (target deps) as 'fespp_deps:$t'..." -ForegroundColor Yellow
        docker build @buildArgs -f (Join-Path $Root "Dockerfile") --target deps -t "fespp_deps:$t" $Root
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "[ERROR] ParaView / fesapi / fetpapi build failed!" -ForegroundColor Red
            exit 1
        }
        Write-Host "Building Docker image with tag 'fespp_on_trame:$t'..." -ForegroundColor Yellow
        docker build @buildArgs -f (Join-Path $Root "Dockerfile") -t "fespp_on_trame:$t" $Root

        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "[ERROR] Docker build failed!" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        # the copy is the build's input only: gone with the build, so that a
        # `docker build .` run later compiles the GitHub ref, as documented
        Remove-LocalSources
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Image: fespp_on_trame:$t" -ForegroundColor Green
    Write-Host "Source: LOCAL ($SourcePath)" -ForegroundColor Green

} else {
    # GITHUB MODE: No source copy, build with the 'dev' tag unless -Tag names one
    Write-Host "MODE: GITHUB (from https://github.com/F2I-Consulting/fespp)" -ForegroundColor Green
    Write-Host ""

    $t = if ($Tag) { $Tag } else { "dev" }
    Write-Host "Building Docker image with tag 'fespp_on_trame:$t'..." -ForegroundColor Yellow
    docker build @buildArgs -f (Join-Path $Root "Dockerfile") -t "fespp_on_trame:$t" $Root

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Docker build failed!" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Image: fespp_on_trame:$t" -ForegroundColor Green
    Write-Host "Source: GITHUB (the FESPP_GIT_TAG ref pinned in the Dockerfile)" -ForegroundColor Green
}

Write-Host ""
