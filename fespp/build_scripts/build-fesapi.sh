#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir
wget https://github.com/F2I-Consulting/fesapi/archive/refs/tags/v2.12.2.0.tar.gz
mkdir fesapi
tar -xzpf v2.12.2.0.tar.gz -C fesapi --strip-components=1
mkdir build-fesapi
cd ${build_root_dir}/build-fesapi
cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DWITH_RESQML2_2=ON \
    -DMINIZIP_INCLUDE_DIR=/work/ttl/dependencies/install-minizip/include \
    -DMINIZIP_LIBRARY_RELEASE=/work/ttl/dependencies/install-minizip/lib/libminizip.a \
    -DMINIZIP_LIBRARY_DEBUG=/work/ttl/dependencies/install-minizip/lib/libminizip.a \
    ../fesapi
make -j$(nproc)
cmake --install .