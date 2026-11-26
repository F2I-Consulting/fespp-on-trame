#!/bin/bash
# Build and install fesapi, the RESQML/EPC library FESPP reads data with,
# with RESQML 2.2 support, against the static Minizip build.
# A failed patch, configure or compile stops the image build here, rather
# than leaving an empty install that fetpapi then cannot find.
set -e
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

curl -L -o fesapi.tar.gz https://github.com/F2I-Consulting/fesapi/archive/refs/tags/v2.15.0.0.tar.gz
mkdir fesapi
tar -xzpf fesapi.tar.gz -C fesapi --strip-components=1
rm -f fesapi.tar.gz
# Local patches (fespp/build_scripts/patches/fesapi/*.patch), in name order
for p in /root/patches/fesapi/*.patch; do
    [ -e "$p" ] || continue
    echo "Applying $(basename "$p")..."
    patch -p1 -d fesapi < "$p"
done

mkdir build-fesapi
cd ${build_root_dir}/build-fesapi
cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DWITH_RESQML2_2=ON \
    -DWITH_EXAMPLE=ON \
    -DCMAKE_INSTALL_PREFIX=${build_root_dir}/install-fesapi/ \
    -DMINIZIP_INCLUDE_DIR=${build_root_dir}/dependencies/install-minizip/include \
    -DMINIZIP_LIBRARY_RELEASE=${build_root_dir}/dependencies/install-minizip/lib/libminizip.a \
    -DMINIZIP_LIBRARY_DEBUG=${build_root_dir}/dependencies/install-minizip/lib/libminizip.a \
    ${build_root_dir}/fesapi
make -j${FESPP_BUILD_JOBS:-$(nproc)}
cmake --install .
rm -Rf ${build_root_dir}/fesapi
rm -Rf ${build_root_dir}/build-fesapi