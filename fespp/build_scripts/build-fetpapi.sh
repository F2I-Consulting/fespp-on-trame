#!/bin/bash
# Build and install fetpapi, the ETP client library FESPP uses for ETP/OSDU
# sources, against the fesapi and static Avro installs.
set -euo pipefail

build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

FETPAPI_VERSION=${FETPAPI_GIT_TAG:-ef57fe7add6af7f6c0de3757d406c691e75cca1c}
# A release tag ("v0.5.0.0") or a commit sha. ef57fe7, fetpapi's dev branch
# past v0.5.0.0, builds against fesapi 2.15 and carries the ResumeSession
# that keeps an OSDU store from answering "Session not found or expired" on
# a reconnection.
case "${FETPAPI_VERSION}" in
    v*) FETPAPI_URL=https://github.com/F2I-Consulting/fetpapi/archive/refs/tags/${FETPAPI_VERSION}.tar.gz ;;
    *)  FETPAPI_URL=https://github.com/F2I-Consulting/fetpapi/archive/${FETPAPI_VERSION}.tar.gz ;;
esac

echo "Downloading fetpapi ${FETPAPI_VERSION}..."
curl -L -o fetpapi.tar.gz ${FETPAPI_URL}
mkdir -p fetpapi
tar -xzpf fetpapi.tar.gz -C fetpapi --strip-components=1
rm -f fetpapi.tar.gz
# Local patches (fespp/build_scripts/patches/fetpapi/*.patch), in name order
for p in /root/patches/fetpapi/*.patch; do
    [ -e "$p" ] || continue
    echo "Applying $(basename "$p")..."
    patch -p1 -d fetpapi < "$p"
done

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

cmake --build . --parallel ${FESPP_BUILD_JOBS:-$(nproc)} || { echo "Build failed"; exit 1; }
cmake --install . || { echo "Install failed"; exit 1; }

# Workaround for fetpapi v0.5.0.0: src/CMakeLists.txt lists the etp headers as
# FETPAPI_ETP_HEADERS while its INSTALL(FILES ${FETPAPI_HEADERS} ... etp) rule
# reads the other list, so ClientSessionLaunchers.h and its siblings are not
# installed and FESPP cannot compile. Copy them from the source tree, which
# gives the installed layout FESPP expects. From 0.6 (sources under
# src/fetpapi/etp) fetpapi installs them itself.
if [ -d ${build_root_dir}/fetpapi/src/etp ]; then
    cp ${build_root_dir}/fetpapi/src/etp/*.h ${build_root_dir}/install-fetpapi/include/fetpapi/etp/
fi

# fetpapi v0.5 installs the handlers under etp/protocolHandlers, while FESPP
# (up to fot-v1.2.0) includes <fetpapi/etp/ProtocolHandlers/...>, which fails
# on a case-sensitive file system. A symlink, never a copy, provides the
# capitalised path: the headers rely on `#pragma once`, which GCC deduplicates
# by file identity, so a copied directory makes every header exist twice and
# every class is redefined.
ln -sfn protocolHandlers ${build_root_dir}/install-fetpapi/include/fetpapi/etp/ProtocolHandlers

# Drop the sources and the build tree to keep the image layer small.
rm -Rf ${build_root_dir}/fetpapi
rm -Rf ${build_root_dir}/build-fetpapi

echo "fetpapi ${FETPAPI_VERSION} build completed successfully"
