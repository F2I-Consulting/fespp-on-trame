#!/bin/bash
# Build script for fespp-on-trame Docker image
# Usage:
#   ./build.sh                                    -> Build from GitHub (tag: dev)
#   ./build.sh /path/to/fespp/src                 -> Build from local source (tag: local)

set -e

SOURCE_PATH="${1:-}"
LOCAL_SRC_DIR="fespp-src-local"

echo "========================================"
echo "FESPP-ON-TRAME Docker Build Script"
echo "========================================"
echo ""

# Clean up existing fespp-src-local directory
if [ -d "$LOCAL_SRC_DIR" ]; then
    echo "Cleaning up existing $LOCAL_SRC_DIR..."
    rm -rf "$LOCAL_SRC_DIR"
fi

if [ -n "$SOURCE_PATH" ]; then
    # LOCAL MODE: Copy source and build with 'local' tag
    echo "MODE: LOCAL (from $SOURCE_PATH)"
    echo ""

    if [ ! -d "$SOURCE_PATH" ]; then
        echo "[ERROR] Source path does not exist: $SOURCE_PATH"
        exit 1
    fi

    if [ ! -f "$SOURCE_PATH/CMakeLists.txt" ]; then
        echo "[ERROR] CMakeLists.txt not found in: $SOURCE_PATH"
        echo "Make sure you're pointing to the FESPP source root directory."
        exit 1
    fi

    echo "Copying FESPP source from $SOURCE_PATH to $LOCAL_SRC_DIR..."
    mkdir -p "$LOCAL_SRC_DIR"
    cp -R "$SOURCE_PATH"/* "$LOCAL_SRC_DIR"/
    echo "[OK] Source copied"
    echo ""

    echo "Building Docker image with tag 'fespp_on_trame:local'..."
    docker build -f Dockerfile -t fespp_on_trame:local .

    if [ $? -ne 0 ]; then
        echo ""
        echo "[ERROR] Docker build failed!"
        exit 1
    fi

    echo ""
    echo "========================================"
    echo "Build completed successfully!"
    echo "========================================"
    echo "Image: fespp_on_trame:local"
    echo "Source: LOCAL ($SOURCE_PATH)"

else
    # GITHUB MODE: No source copy, build with 'dev' tag
    echo "MODE: GITHUB (from https://github.com/F2I-Consulting/fespp)"
    echo ""

    echo "Building Docker image with tag 'fespp_on_trame:dev'..."
    docker build -f Dockerfile -t fespp_on_trame:dev .

    if [ $? -ne 0 ]; then
        echo ""
        echo "[ERROR] Docker build failed!"
        exit 1
    fi

    echo ""
    echo "========================================"
    echo "Build completed successfully!"
    echo "========================================"
    echo "Image: fespp_on_trame:dev"
    echo "Source: GITHUB (dev branch)"
fi

echo ""
