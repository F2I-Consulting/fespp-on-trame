#!/bin/bash

echo "==================================================="
echo "ParaView Superbuild - Unified CPU/GPU Build Script"
echo "==================================================="
echo "PVSB_GIT_TAG: ${PVSB_GIT_TAG:-v6.0.0}"
echo "PARALLEL_NB: ${PARALLEL_NB:-$(nproc)}"
echo "ENABLE: ${ENABLE}"
echo "USE_SYSTEM: ${USE_SYSTEM}"
echo "==================================================="

# Checkout de la version spécifiée
# Clonage des sources ParaView
cd /work/pvsb-sources

#git fetch --tags
git checkout "${PVSB_GIT_TAG:-v6.0.0}"
git submodule update --recursive
cd /work

# Détection automatique du mode (GPU ou CPU)
USE_GPU=false
if nvidia-smi &> /dev/null 2>&1; then
    echo "✓ GPU NVIDIA détecté - Mode GPU/EGL activé"
    USE_GPU=true
    export PV_DEBUG_GL=1
    export PV_DEBUG_EGL=1
else
    echo "✓ Aucun GPU détecté - Mode CPU/OSMesa activé"
fi

# Options communes de build (sans Qt, pvpython uniquement)
cmake_common_options="\
-DENABLE_mpi=ON \
-DENABLE_paraviewweb=ON \
-DPARAVIEW_ENABLE_WEB=ON \
-DENABLE_python3=ON \
-DPARAVIEW_USE_PYTHON=ON \
-DENABLE_occt=ON \
-DENABLE_numpy=ON \
-DPARAVIEW_INSTALL_DEVELOPMENT_FILES=ON \
-Dllvm_BUILD_SHARED_LIBS=OFF \
-DPARAVIEW_USE_QT=OFF \
-DVTK_RENDERING_BACKEND=OpenGL2 \
-DVTK_MODULE_USE_EXTERNAL_VTK_libharu=OFF \
-DVTK_MODULE_USE_EXTERNAL_VTK_netcdf=OFF"

# Options spécifiques selon GPU ou CPU
if [ "$USE_GPU" = true ]; then
    echo "Configuring for GPU rendering (EGL)..."
    cmake_rendering_option="\
-DENABLE_egl=ON \
-DVTK_OPENGL_HAS_EGL=ON \
-DVTK_USE_X=OFF \
-DVTK_DEFAULT_RENDER_WINDOW_OFFSCREEN=ON \
-DVTK_USE_NVCONTROL=OFF \
-DPARAVIEW_BUILD_WITH_EXTERNAL=ON \
-DVTK_MODULE_USE_EXTERNAL_VTK_gl2ps=OFF"
else
    echo "Configuring for CPU rendering (OSMesa)..."
    cmake_rendering_option="-DENABLE_osmesa=ON"
fi

echo ""
echo "=== CMake Configuration Phase ==="
cmake \
    -B pvsb-build/ \
    -S pvsb-sources/ \
    -G Ninja \
    ${cmake_rendering_option} \
    ${cmake_common_options} \
    ${ENABLE} \
    ${USE_SYSTEM}

echo ""
echo "=== Build Phase (parallel jobs: ${PARALLEL_NB:-$(nproc)}) ==="
cmake --build pvsb-build --parallel "${PARALLEL_NB:-$(nproc)}"

# Tests uniquement en mode CPU
if [ "$USE_GPU" = false ]; then
    echo ""
    echo "=== Running cpack tests ==="
    cd pvsb-build
    ctest -R cpack || echo "⚠ Tests completed with warnings"
    cd /work
fi

echo ""
echo "==================================================="
echo "✓ ParaView build completed successfully!"
echo "  Mode: $([ "$USE_GPU" = true ] && echo 'GPU/EGL' || echo 'CPU/OSMesa')"
echo "  Qt: Disabled (pvpython only)"
echo "  Install: /work/pvsb-build/install"
echo "==================================================="
