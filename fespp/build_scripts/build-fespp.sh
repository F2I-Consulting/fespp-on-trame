#!/bin/bash
# Build the FESPP ParaView plugin against the fesapi, fetpapi and Avro installs
# and the ParaView superbuild, then gather its runtime libraries beside it.
#
# Fail the Docker build on any error: otherwise a make failure slips through
# to `cmake --install` and yields a "successful" image whose FESPP plugin is
# stale or missing.
set -euo pipefail
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
cd $build_root_dir

# Local mode when the Dockerfile copied a host FESPP checkout (fespp-src-local,
# optional) into the build root; GitHub mode otherwise.
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
    echo "Repository: https://github.com/F2I-Consulting/fespp (ref: ${FESPP_GIT_TAG:-master})"
    git clone https://github.com/F2I-Consulting/fespp
    cd fespp
    # Pinned ref (Dockerfile ENV FESPP_GIT_TAG): the image always compiles
    # against the FESPP revision this viewer is validated with.
    git checkout "${FESPP_GIT_TAG:-master}"
    cd ${build_root_dir}
    echo "[OK] FESPP cloned from GitHub"
fi

# Local patches (fespp/build_scripts/patches/fespp/*.patch), in name order:
# what this viewer needs of FESPP ahead of the libraries it depends on (the
# sized reads need the patched fesapi). A checkout copied from Windows has
# CRLF line ends and a git patch LF ones: the files a patch touches lose
# their CR first, or no hunk would match.
for p in /root/patches/fespp/*.patch; do
    [ -e "$p" ] || continue
    echo "Applying $(basename "$p")..."
    for f in $(sed -n 's#^+++ b/##p' "$p"); do
        if [ -f "${build_root_dir}/fespp/$f" ]; then
            sed -i 's/\r$//' "${build_root_dir}/fespp/$f"
        fi
    done
    patch -p1 -d ${build_root_dir}/fespp < "$p"
done

echo ""
echo "Building FESPP..."
mkdir -p ${build_root_dir}/build-fespp
cd ${build_root_dir}/build-fespp/
# Release unless FESPP_BUILD_TYPE says otherwise (RelWithDebInfo keeps the
# symbols a debugger needs to name a line, four times the library's size)
cmake \
    -DCMAKE_BUILD_TYPE=${FESPP_BUILD_TYPE:-Release} \
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
make -j${FESPP_BUILD_JOBS:-$(nproc)}
cmake --install .
rm -Rf ${build_root_dir}/fespp
rm -Rf ${build_root_dir}/build-fespp
# The plugin lands in lib/paraview-<major.minor>/plugins/Fespp, named after
# the ParaView it was built against, so the directory is found by glob, never
# hardcoded. `lib/paraview` is a stable link to it, used by the launcher
# (setup/apps.yml), the image check and the test harnesses.
pv_lib_dirs=(/work/ttl/install-fespp/lib/paraview-*)
if [ "${#pv_lib_dirs[@]}" -ne 1 ] || [ ! -f "${pv_lib_dirs[0]}/plugins/Fespp/Fespp.so" ]; then
    echo "[ERROR] expected exactly one lib/paraview-*/plugins/Fespp/Fespp.so, found: ${pv_lib_dirs[*]}" >&2
    exit 1
fi
plugin_dir="${pv_lib_dirs[0]}/plugins/Fespp"
# fesapi and fetpapi go next to the plugin: its RUNPATH is $ORIGIN.
cp -R ${build_root_dir}/install-fesapi/lib/* "${plugin_dir}/."
cp -R ${build_root_dir}/install-fetpapi/lib/*.so* "${plugin_dir}/."
ln -sfn "$(basename "${pv_lib_dirs[0]}")" /work/ttl/install-fespp/lib/paraview
echo "[OK] FESPP plugin: ${plugin_dir}/Fespp.so (stable path /work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so)"