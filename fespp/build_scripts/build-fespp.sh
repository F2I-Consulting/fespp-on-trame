#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

curl -L -o fespp.tar.gz https://github.com/F2I-Consulting/fespp/archive/refs/tags/v3.3.0.tar.gz
mkdir fespp
tar -xzpf fespp.tar.gz -C fespp --strip-components=1
rm -f fespp.tar.gz

mkdir build-fespp

cd ${build_root_dir}/build-fespp/
cmake \
    -DPARAVIEW_PLUGIN_ENABLE_Fespp=ON \
    -DCMAKE_INSTALL_PREFIX=/work/ttl/install-fespp/ \
    -DFESAPI_ROOT=${build_root_dir}/install-fesapi \
    -DParaView_DIR=/work/pvsb-build/superbuild/paraview/build \
    -Dnlohmann_json_DIR=/work/pvsb-build/install/lib/cmake/nlohmann_json \
    -DSQLite3_INCLUDE_DIR=/work/pvsb-build/install/include \
    -DSQLite3_LIBRARY=/work/pvsb-build/install/lib/libsqlite3.so \
    ${build_root_dir}/fespp
make -j$(nproc)
cmake --install .
rm -Rf ${build_root_dir}/fespp
rm -Rf ${build_root_dir}/build-fespp
cp -R ${build_root_dir}/install-fesapi/lib/* /work/ttl/install-fespp/lib/paraview-5.13/plugins/Fespp/.