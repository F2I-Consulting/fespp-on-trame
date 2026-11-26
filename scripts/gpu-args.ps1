# The `docker run` arguments that hand the HOST's GPU to the container.
#
# A helper rather than a line in the image: no image can contain these
# three things, they are resources of the host machine.
#
#   --device=/dev/dxg                          the WSL2 GPU bridge
#   -v <DriverStore>:/usr/lib/wsl/drivers:ro   the VENDOR's driver, without
#                                              which D3D12 has nothing to
#                                              drive and falls back to software
#   -v <cache>:/usr/lib/wsl/lib:ro             libd3d12 / libdxcore, the WSL
#                                              D3D12 runtime
#
# What the image brings on its side: a Mesa recent enough to enable the
# d3d12 driver (Ubuntu 22.04's Mesa does not even try it) and
# vtkEGLRenderWindow, the only render window able to use the hardware
# without an X server. Hardware rendering is well over an order of
# magnitude faster than software rendering on a real grid.
#
# On NVIDIA it is simpler and preferred: the Container Toolkit INJECTS the
# driver into the container, so `--gpus all` replaces the three arguments,
# with no Mesa and no driver store. The function chooses by itself, so a
# machine that gains an NVIDIA card needs no change in the calling scripts.
#
# Nothing is silent: the function SAYS what it found or what is missing,
# and returns an EMPTY array rather than arguments that would make
# `docker run` fail. A container without a GPU is not broken, it renders in
# software, and the application logs that too at its first 3D view
# (view_manager._say_render_backend).

$FesppDriverStore = "C:\Windows\System32\DriverStore\FileRepository"

function Get-FesppGpuArgs {
    param(
        # repository root: the WSL library cache goes under _local
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$Quiet
    )

    function Say($msg, $color) {
        if (-not $Quiet) { Write-Host $msg -ForegroundColor $color }
    }

    # 1. NVIDIA first: a single argument, and the supported path.
    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidia) {
        Say "GPU : NVIDIA detecte, --gpus all" "Green"
        return @("--gpus", "all")
    }

    # 2. Otherwise the WSL2/D3D12 route (AMD, Intel, or NVIDIA without the toolkit).
    if (-not (Test-Path $FesppDriverStore)) {
        Say "GPU : magasin de pilotes Windows introuvable, rendu LOGICIEL." "Yellow"
        return @()
    }

    # The three .so files live INSIDE a WSL distribution, not on the Windows
    # disk: they are copied once into _local (ignored by git, they are
    # Microsoft binaries) so that they can be mounted.
    $cache = Join-Path $Root "_local\wsl-gpu"
    $need = @("libd3d12.so", "libd3d12core.so", "libdxcore.so")
    $missing = $need | Where-Object { -not (Test-Path (Join-Path $cache $_)) }
    if ($missing) {
        $distro = (wsl.exe -l -q 2>$null | ForEach-Object { $_ -replace "`0", "" } |
                   Where-Object { $_.Trim() -and $_ -notmatch "docker-desktop" } |
                   Select-Object -First 1)
        if (-not $distro) {
            Say "GPU : aucune distribution WSL pour y prendre libd3d12, rendu LOGICIEL." "Yellow"
            return @()
        }
        $distro = $distro.Trim()
        New-Item -ItemType Directory -Force $cache | Out-Null
        # "D:\repo\x" -> "/mnt/d/repo/x", the form WSL understands
        $dest = "/mnt/" + $cache.Substring(0, 1).ToLower() + ($cache.Substring(2) -replace "\\", "/")
        wsl.exe -d $distro -e sh -c "cp /usr/lib/wsl/lib/*.so '$dest/'" 2>$null | Out-Null
        $still = $need | Where-Object { -not (Test-Path (Join-Path $cache $_)) }
        if ($still) {
            Say "GPU : libd3d12/libdxcore introuvables dans $distro, rendu LOGICIEL." "Yellow"
            return @()
        }
        Say "GPU : runtime D3D12 copie depuis $distro vers _local\wsl-gpu" "DarkGray"
    }

    Say "GPU : WSL2/D3D12 (device dxg + magasin de pilotes)" "Green"
    return @(
        "--device=/dev/dxg",
        "-v", "${FesppDriverStore}:/usr/lib/wsl/drivers:ro",
        "-v", "${cache}:/usr/lib/wsl/lib:ro"
    )
}
