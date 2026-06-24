#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

# Check if local FESPP source is available (copied by Dockerfile from fespp-src-local)
if [ -f ${build_root_dir}/fespp/CMakeLists.txt ]; then
    echo "=========================================="
    echo "LOCAL MODE: Using FESPP source from host"
    echo "=========================================="
    echo "Source already present in ${build_root_dir}/fespp"
    echo "[OK] Local FESPP source detected"
else
    echo "=========================================="
    echo "GITHUB MODE: Cloning FESPP from GitHub"
    echo "=========================================="
    echo "Repository: https://github.com/F2I-Consulting/fespp (branch: master)"
    git clone https://github.com/F2I-Consulting/fespp
    cd fespp
    git checkout master
    cd ${build_root_dir}
    echo "[OK] FESPP cloned from GitHub"
fi

echo ""
echo "Building FESPP..."
mkdir -p ${build_root_dir}/build-fespp
cd ${build_root_dir}/build-fespp/
cmake \
    -DPARAVIEW_PLUGIN_ENABLE_Fespp=ON \
    -DCMAKE_INSTALL_PREFIX=/work/ttl/install-fespp/ \
    -DFESAPI_ROOT=${build_root_dir}/install-fesapi \
    -DParaView_DIR=/work/pvsb-build/superbuild/paraview/build \
    -Dnlohmann_json_DIR=/work/pvsb-build/install/lib/cmake/nlohmann_json \
    -DSQLite3_INCLUDE_DIR=/work/pvsb-build/install/include \
    -DSQLite3_LIBRARY=/work/pvsb-build/install/lib/libsqlite3.so \
    -DWITH_ETP_SSL=ON \
    -DFETPAPI_INCLUDE_DIR=${build_root_dir}/install-fetpapi/include \
    -DFETPAPI_LIBRARY_RELEASE=${build_root_dir}/install-fetpapi/lib/libFetpapi.so \
    -DAVRO_INCLUDE_DIR=${build_root_dir}/dependencies/install-avro/include \
    -DAVRO_LIBRARY=${build_root_dir}/dependencies/install-avro/lib/libavrocpp_s.a \
    ${build_root_dir}/fespp
make -j$(nproc)
cmake --install .
rm -Rf ${build_root_dir}/fespp
rm -Rf ${build_root_dir}/build-fespp
cp -R ${build_root_dir}/install-fesapi/lib/* /work/ttl/install-fespp/lib/paraview-6.0/plugins/Fespp/.
cp -R ${build_root_dir}/install-fetpapi/lib/*.so* /work/ttl/install-fespp/lib/paraview-6.0/plugins/Fespp/.