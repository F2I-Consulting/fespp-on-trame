#!/bin/bash
cd /work

cd /work/pvsb-sources && git checkout "${PVSB_GIT_TAG:-'v5.12.1'}" && git submodule update --recursive && cd ..

cmake_options="-DENABLE_mpi=ON -DENABLE_paraviewweb=ON -DENABLE_python3=ON -DENABLE_occt=ON -DENABLE_numpy=ON"

echo $RENDERING_BACKEND

if [ $RENDERING_BACKEND = "OSMESA" ]
then
    echo "Enabling OSMESA"
    cmake_rendering_option="-DENABLE_osmesa=ON"
elif [ $RENDERING_BACKEND = "MESA" ]
then
    echo "Enabling MESA"
    cmake_rendering_option="-DENABLE_mesa=ON"
elif [ $RENDERING_BACKEND = "QT5" ]
then
    echo "Enabling qt5"
    cmake_rendering_option="-DENABLE_qt5=ON"
elif [ $RENDERING_BACKEND = "EGL" ]
then
    echo "Enabling EGL"
    cmake_rendering_option="-DENABLE_egl=ON"
fi

cmake \
    -B pvsb-build/ \
    -S pvsb-sources/ \
    -GNinja \
    ${cmake_rendering_option} \
    ${cmake_options} \
    ${ENABLE} \
    -Dllvm_BUILD_SHARED_LIBS=OFF \
    ${USE_SYSTEM}

cmake --build pvsb-build --parallel "${PARALLEL_NB:-4}"
cd pvsb-build && ctest -R cpack
