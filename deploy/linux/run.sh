#!/usr/bin/env bash
# The public site on Linux: the application in a container on 127.0.0.1:8090
# under the /fespp prefix, behind the host's Apache (deploy/apache/setup.sh).
# The container restarts by itself, after a reboot too.
#
#   bash deploy/linux/run.sh             rebuild from this checkout, then replace the site
#   bash deploy/linux/run.sh --no-build  replace the site with the image already built
#   bash deploy/linux/run.sh --rollback  back to the previous version (each update keeps it, stopped)
#   bash deploy/linux/run.sh --status    what runs, and whether the page answers
#   bash deploy/linux/run.sh --stop      stop the site
#
# Options: --port 8090, --prefix /fespp, --name fespp, --gpu or --no-gpu
# (by default the GPU when Docker reaches an NVIDIA one).
set -euo pipefail
cd "$(dirname "$0")/../.."   # the repository root

PORT=8090
PREFIX=/fespp
NAME=fespp
IMAGE=fespp_on_trame:deploy
ACTION=update
GPU=auto
while [ $# -gt 0 ]; do
    case "$1" in
        --no-build) ACTION=nobuild ;;
        --rollback) ACTION=rollback ;;
        --status) ACTION=status ;;
        --stop) ACTION=stop ;;
        --port) PORT="$2"; shift ;;
        --prefix) PREFIX="$2"; shift ;;
        --name) NAME="$2"; shift ;;
        --gpu) GPU=yes ;;
        --no-gpu) GPU=no ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "[ERROR] unknown option: $1 (see --help)"; exit 1 ;;
    esac
    shift
done
PREV="${NAME}_prev"
URL="http://127.0.0.1:${PORT}${PREFIX}/index.html"

exists() { docker container inspect "$1" >/dev/null 2>&1; }

answers() {   # the page answers within about a minute
    command -v curl >/dev/null || { echo "(curl missing: page not checked)"; return 0; }
    for _ in $(seq 1 60); do
        curl -fsS -o /dev/null "$URL" 2>/dev/null && return 0
        sleep 1
    done
    return 1
}

start() {     # $1 = yes|no: give the container the GPU
    local gpu_args=()
    [ "$1" = yes ] && gpu_args=(--gpus all)
    docker run -d --name "$NAME" --restart unless-stopped \
        -p "127.0.0.1:${PORT}:80" \
        -e "TRAME_URL_PREFIX=${PREFIX}" -e "TRAME_USE_HOST=wss://USE_HOST${PREFIX}" \
        ${gpu_args[@]+"${gpu_args[@]}"} "$IMAGE" >/dev/null
}

case "$ACTION" in
    stop)
        docker stop "$NAME" >/dev/null && echo "[OK] $NAME stopped (bash deploy/linux/run.sh --no-build starts it again)"
        ;;
    status)
        docker ps -a --filter "name=^${NAME}" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
        if answers; then echo "[OK] $URL answers"; else echo "[ERROR] $URL does not answer: docker logs --tail 50 $NAME"; fi
        ;;
    rollback)
        exists "$PREV" || { echo "[ERROR] no previous version ($PREV) to go back to"; exit 1; }
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        docker rename "$PREV" "$NAME"
        docker update --restart unless-stopped "$NAME" >/dev/null
        docker start "$NAME" >/dev/null
        if answers; then echo "[OK] back to the previous version: $URL"; else echo "[ERROR] $URL does not answer: docker logs --tail 50 $NAME"; exit 1; fi
        ;;
    update|nobuild)
        if [ "$ACTION" = update ]; then
            bash build.sh --tag deploy   # the heavy stages come from Docker's cache
        fi
        docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "[ERROR] no image $IMAGE: run bash deploy/linux/run.sh (without --no-build)"; exit 1; }
        # the running version becomes the previous one, stopped, for --rollback
        if exists "$NAME"; then
            docker rm -f "$PREV" >/dev/null 2>&1 || true
            docker stop "$NAME" >/dev/null
            docker update --restart no "$NAME" >/dev/null
            docker rename "$NAME" "$PREV"
        fi
        use_gpu=no
        if [ "$GPU" = yes ] || { [ "$GPU" = auto ] && docker info 2>/dev/null | grep -qi nvidia; }; then
            use_gpu=yes
        fi
        start "$use_gpu"
        if ! answers && [ "$use_gpu" = yes ] && [ "$GPU" = auto ]; then
            # a GPU Docker sees but the container cannot use: software rendering
            echo "[WARN] no answer with the GPU: restarting with software rendering"
            docker rm -f "$NAME" >/dev/null
            use_gpu=no
            start no
        fi
        if answers; then
            # images no container uses any more (each update leaves one)
            docker image prune -f >/dev/null
            echo "[OK] $URL ($( [ "$use_gpu" = yes ] && echo GPU || echo 'software rendering' ))"
            echo "     back to the previous version if needed: bash deploy/linux/run.sh --rollback"
        else
            echo "[ERROR] $URL does not answer: docker logs --tail 50 $NAME"
            echo "        back to the previous version: bash deploy/linux/run.sh --rollback"
            exit 1
        fi
        ;;
esac
