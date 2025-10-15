#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir
git clone https://github.com/F2I-Consulting/fespp
mkdir build-fespp
cd fespp
git checkout dev
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