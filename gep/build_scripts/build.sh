#!/bin/bash
build_root_dir=${GEP_BUILD_ROOT_DIR:-"/work/ttl/gep"}
cd $build_root_dir
mkdir build-gep
cmake \
    -S gridextractorplugin \
    -B build-gep \
    -DCMAKE_BUILD_TYPE=Release \
    -DParaView_DIR=/work/pvsb-build/superbuild/paraview/build \
    -DBUILD_PVPLUGIN=ON \
    -DHAVE_RESQMLREADER=ON \
    -DFESAPI_INCLUDE_DIR=/work/ttl/build-fesapi/install/include \
    -DFESAPI_DIR=/work/ttl/build-fesapi/ \
    -DSQLite3_INCLUDE_DIR=/work/pvsb-build/install/include \
    -DSQLite3_LIBRARY=/work/pvsb-build/install/lib/libsqlite3.so

cmake --build build-gep --parallel $(nproc)
cmake --install build-gep
