#!/bin/bash
# Build script for fetpapi v0.4.0.0
set -euo pipefail

build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

FETPAPI_VERSION=v0.4.0.0
FETPAPI_URL=https://github.com/F2I-Consulting/fetpapi/archive/refs/tags/${FETPAPI_VERSION}.tar.gz

echo "Downloading fetpapi ${FETPAPI_VERSION}..."
curl -L -o fetpapi.tar.gz ${FETPAPI_URL}
mkdir -p fetpapi
tar -xzpf fetpapi.tar.gz -C fetpapi --strip-components=1
rm -f fetpapi.tar.gz

mkdir -p build-fetpapi
cd ${build_root_dir}/build-fetpapi

cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=${build_root_dir}/install-fetpapi \
    -DFESAPI_ROOT=${build_root_dir}/install-fesapi \
    -DCMAKE_PREFIX_PATH=${build_root_dir}/install-fesapi \
    -DAVRO_ROOT=${build_root_dir}/dependencies/install-avro \
    -DAVRO_USE_STATIC_LIBS=ON \
    -DWITH_FESAPI=ON \
    -DFESAPI_ROOT=${build_root_dir}/install-fesapi \
    ${build_root_dir}/fetpapi

cmake --build . || { echo "Build failed"; exit 1; }
cmake --install . || { echo "Install failed"; exit 1; }

# Cleanup
rm -Rf ${build_root_dir}/fetpapi
rm -Rf ${build_root_dir}/build-fetpapi

echo "fetpapi ${FETPAPI_VERSION} build completed successfully"
