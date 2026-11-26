#!/usr/bin/env bash
# Build the fespp_on_trame image on Linux (the twin of build.ps1).
#
#   bash build.sh                          FESPP from GitHub (the fot-* tag pinned in the Dockerfile)
#   bash build.sh <path-to-fespp-sources>  FESPP compiled from a local checkout instead
#   bash build.sh ... --tag <name>         another image tag than fespp_on_trame:local
#
# The first build compiles ParaView and FESPP: one to two hours. Later builds
# reuse Docker's cache and take minutes.
set -euo pipefail
cd "$(dirname "$0")"   # every path below is relative to the repository root

TAG=local
SRC=""
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) SRC="$1"; shift ;;
    esac
done

command -v docker >/dev/null || { echo "[ERROR] Docker is not installed: https://docs.docker.com/engine/install/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "[ERROR] Docker does not answer: is it running, and is this user in the docker group?"; exit 1; }

# the toolchain image (compilers, CMake, paraview-superbuild), built once
if ! docker image inspect paraview:6.0.x >/dev/null 2>&1; then
    echo "== Toolchain image paraview:6.0.x (once)"
    docker build -t paraview:6.0.x -f Dockerfile.paraview .
fi

# fespp-src-local is the build context's copy of local FESPP sources; without
# it the Dockerfile clones GitHub, so a copy left by an earlier build must go
rm -rf fespp-src-local
if [ -n "$SRC" ]; then
    [ -f "$SRC/CMakeLists.txt" ] || { echo "[ERROR] $SRC is not a FESPP checkout (no CMakeLists.txt)"; exit 1; }
    echo "== FESPP from $SRC"
    cp -r "$SRC" fespp-src-local
    trap 'rm -rf fespp-src-local' EXIT
else
    echo "== FESPP from GitHub (the tag pinned in the Dockerfile)"
fi

# ParaView and fesapi/fetpapi first, as a build of their own: a FESPP compile
# error then never costs the ParaView superbuild again
echo "== ParaView, fesapi, fetpapi (cached after the first build)"
docker build -f Dockerfile --target deps -t "fespp_deps:$TAG" .
echo "== Application image fespp_on_trame:$TAG"
docker build -f Dockerfile -t "fespp_on_trame:$TAG" .
echo "[OK] fespp_on_trame:$TAG"
echo "     public site: bash deploy/linux/run.sh    quick try: docker run -p 8080:80 fespp_on_trame:$TAG"
