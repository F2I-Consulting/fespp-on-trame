#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir
git clone https://github.com/F2I-Consulting/fesapi.git
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
