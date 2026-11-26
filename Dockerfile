# ============================================================================
# Builder stages - compile ParaView, then fesapi/fetpapi, then FESPP
# ============================================================================
# paraview:6.0.x (Dockerfile.paraview) is the toolchain only: compilers,
# CMake and a clone of paraview-superbuild. The ParaView version actually
# built is PVSB_GIT_TAG below (see build.bash); the base image's tag does not
# name it.
#
# The build is split into named stages, and build.ps1 builds `--target deps`
# before the whole image. A build that fails keeps none of its long steps in
# BuildKit's cache, so the ParaView superbuild, by far the longest step,
# would run again; a `--target deps` build that succeeds is cached, so a
# later FESPP failure costs minutes, not the superbuild.
FROM paraview:6.0.x AS pvbuild

# 8 parallel jobs rather than one per CPU: the build may share the Docker VM
# with a running instance of the application, which must keep enough memory
# while ParaView compiles.
ENV PARALLEL_NB=8
# ParaView 6.1.1 (VTK 9.6.2). Only a released ParaView is a base to build on,
# never a release candidate.
ENV PVSB_GIT_TAG="v6.1.1"
ENV ENABLE="-DENABLE_hdf5=ON"
ENV USE_SYSTEM="-DUSE_SYSTEM_hdf5=ON -DUSE_SYSTEM_zlib=ON"

# This tree's superbuild script, run by bash: it relies on bash features
# (pipefail) that dash, the image's `sh`, lacks.
COPY build.bash /work/build.bash
RUN bash /work/build.bash

# fesapi and fetpapi, the libraries FESPP links, with their own dependencies
# (built against the system HDF5, not ParaView's).
FROM pvbuild AS deps
ENV FESPP_BUILD_ROOT_DIR=/work/ttl

# System packages fesapi and fetpapi build against.
RUN apt update && apt install -y libboost-all-dev sqlite3 libxml2-dev libfreetype-dev

# fesapi 2.15 needs CMake 3.29 or later. The toolchain image's 3.28 stays the
# one ParaView is built with: changing it there would throw the superbuild's
# cache away.
RUN mkdir -p /opt/cmake/3.31.6 && \
    curl -L https://cmake.org/files/v3.31/cmake-3.31.6-linux-x86_64.tar.gz | \
    tar -xz -C /opt/cmake/3.31.6 --strip-components=1 && \
    ln -sf /opt/cmake/3.31.6/bin/cmake /usr/bin/cmake && \
    ln -sf /opt/cmake/3.31.6/bin/cpack /usr/bin/cpack && \
    ln -sf /opt/cmake/3.31.6/bin/ctest /usr/bin/ctest && \
    cmake --version

# Each library's script and patches are copied just before its own build:
# a change on the fetpapi side does not compile fesapi again.
COPY ./fespp/build_scripts/build-fesapi-dependencies.sh /root/build-fesapi-dependencies.sh
COPY ./fespp/build_scripts/build-fesapi.sh /root/build-fesapi.sh
# Local patches applied to the fesapi, fetpapi and FESPP sources before their
# build (fespp/build_scripts/patches/<lib>/*.patch, git format-patch files, in
# name order; an empty folder applies nothing).
COPY ./fespp/build_scripts/patches/fesapi/ /root/patches/fesapi/

RUN bash /root/build-fesapi-dependencies.sh
# Compile parallelism of fesapi, fetpapi and FESPP: empty = every core. On a
# PC that also runs the app containers, twelve parallel compilations starve
# the Docker engine (`docker build --build-arg FESPP_BUILD_JOBS=6`).
ARG FESPP_BUILD_JOBS=
ENV FESPP_BUILD_JOBS=${FESPP_BUILD_JOBS}
RUN bash /root/build-fesapi.sh
COPY ./fespp/build_scripts/build-fetpapi-dependencies.sh /root/build-fetpapi-dependencies.sh
RUN bash /root/build-fetpapi-dependencies.sh
COPY ./fespp/build_scripts/build-fetpapi.sh /root/build-fetpapi.sh
COPY ./fespp/build_scripts/patches/fetpapi/ /root/patches/fetpapi/
# fetpapi: a release tag, or a commit sha to try an upstream fix ahead of a
# release (build-fetpapi.sh; `docker build --build-arg FETPAPI_GIT_TAG=<sha>`).
# The sized-reads patch (patches/fetpapi) is written against ef57fe7, the
# dev commit that moves fetpapi to fesapi 2.15, past v0.5.0.0.
ARG FETPAPI_GIT_TAG=ef57fe7add6af7f6c0de3757d406c691e75cca1c
ENV FETPAPI_GIT_TAG=${FETPAPI_GIT_TAG}
RUN bash /root/build-fetpapi.sh

# FESPP. Its build script is copied in this stage, after fesapi and fetpapi
# are built: copied alongside their scripts, any edit of it would rebuild
# both libraries.
FROM deps AS builder
COPY ./fespp/build_scripts/build-fespp.sh /root/build-fespp.sh
# FESPP's own patches with it, for the same reason: a patch of the plugin made
# again must not rebuild fesapi and fetpapi
COPY ./fespp/build_scripts/patches/fespp/ /root/patches/fespp/
# The plugin's build type: Release for what is delivered; `docker build
# --build-arg FESPP_BUILD_TYPE=RelWithDebInfo` for an image a debugger reads.
ARG FESPP_BUILD_TYPE=Release
ENV FESPP_BUILD_TYPE=${FESPP_BUILD_TYPE}

# Build mode: local (sources copied from the host) or github (git clone).
# FESPP_GIT_TAG is the FESPP ref of the github mode. It is pinned, like
# PVSB_GIT_TAG, so that every branch or tag of this repository rebuilds
# against the FESPP state it was validated with (`fot-*` anchor tags on
# F2I-Consulting/fespp); a floating `master` would break older branches
# whenever FESPP moves.
# Set here rather than at the top: an ENV line invalidates the cache of every
# later layer, and above build.bash it would rerun the whole ParaView
# superbuild.
ENV FESPP_GIT_TAG="fot-v2.0.0-a1"
COPY fespp-src-local* ${FESPP_BUILD_ROOT_DIR}/fespp/

RUN bash /root/build-fespp.sh

# ============================================================================
# VTK patches - fixes missing from ParaView's VTK, applied to the built tree:
# only the patched sources recompile (seconds), not the superbuild
# ============================================================================
# vtk-9.6-batched-mapper-texture-unit.patch: VTK 9.6's composite mapper loads
# a 1x1 magenta "texture error" prototype in each of its batched mappers (one
# per distinct block layout, so one per coloured well-log channel) and never
# releases its texture unit. A wellbore with many channels exhausts the
# context's 32 texture units, the wellhead's 3D text finds none free, and the
# view's background renders magenta, in GPU and software rendering alike.
# The patch leaves the headers untouched, so FESPP, compiled against the
# unpatched build, stays valid.
# `patch -N` fails the build when a patch no longer applies (a ParaView
# upgrade that moved the source, or a VTK that already has the fix): a patch
# is never skipped silently; delete the patch file in that case.
FROM builder AS vtkpatch
COPY patches/ /work/patches/
RUN set -eu; \
    cd /work/pvsb-build/superbuild/paraview/src; \
    for p in /work/patches/vtk-*.patch; do \
        echo "applying $p"; patch -p1 -N -i "$p"; \
    done; \
    cd /work/pvsb-build/superbuild/paraview/build; \
    ninja -j "${PARALLEL_NB}" install > /tmp/vtkpatch-install.log; \
    grep -- "-- Installing:" /tmp/vtkpatch-install.log

# ============================================================================
# Slim stage - what the runtime copies, without what only a build reads
# ============================================================================
# Deleting files in the runtime stage would not shrink the image (a later
# layer only masks an earlier one): the trimming happens here, and the
# runtime copies the result. Removed, several hundred MB in all: headers,
# static libraries (libpython3.12.a included), Python's own test suite, the
# build tools the numpy build leaves in ParaView's site-packages (Cython,
# pythran, pip, meson, setuptools...), docs and locales. None is read at run
# time: when anything asks for setuptools, pkg_resources or packaging,
# pvpython imports them from the venv. Of /work/ttl only install-fespp is
# read: Fespp.so finds fesapi and fetpapi next to it (RUNPATH $ORIGIN), and
# PropertyKindMapping.xml there too.
FROM vtkpatch AS slim
RUN set -eu; \
    cd /work/pvsb-build/install; \
    rm -rf include lib/cmake lib/pkgconfig share/doc share/locale share/man \
           lib/python3.12/test lib/python3.12/idlelib; \
    find . -name '*.a' -delete; \
    cd lib/python3.12/site-packages; \
    rm -rf Cython Cython-*.egg-info cython.py pyximport \
           pythran pythran-*.dist-info beniget beniget-*.egg-info \
           gast gast-*.egg-info ply ply-*.egg-info \
           mesonbuild meson-*.egg-info mesonpy meson_python-*.dist-info \
           pyproject_metadata pyproject_metadata-*.dist-info \
           flit_core flit_core-*.dist-info wheel wheel-*.dist-info \
           pip pip-*.dist-info setuptools setuptools-*.dist-info \
           pkg_resources _distutils_hack distutils-precedence.pth; \
    cd /work/pvsb-build/install/bin; \
    rm -f cython cythonize cygdb pythran pythran-config meson meson-real \
          pip3 pip3.12 wheel; \
    rm -rf /work/ttl/install-fespp/include; \
    find /work/ttl/install-fespp -name '*.a' -delete; \
    test -f /work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so; \
    du -sh /work/pvsb-build/install /work/ttl/install-fespp

# ============================================================================
# Runtime stage
# ============================================================================
FROM kitware/trame:uv-1.2-glvnd-runtime-ubuntu22.04 AS runtime

# NVIDIA Container Toolkit: expose every GPU, with the graphics capability
# that rendering needs.
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute

# Render window: EGL, never GLX.
#
# Without an X server, as in a container, vtkXOpenGLRenderWindow can only
# fall back to software rendering (after logging "bad X server connection").
# vtkEGLRenderWindow is the only one of the three render windows built into
# this ParaView that can drive a GPU without a display. It is set for every
# container: with no GPU passed in, it renders in software, pixel-identical
# to the GLX fallback (the visual baselines do not change); with a GPU, it
# uses it.
ENV VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow

# WSL's D3D12 runtime, when the host mounts it (see below). Appended to the
# path inherited from the trame image, which already lists the NVIDIA
# Container Toolkit's injection directories: the dynamic linker ignores a
# missing directory, so this has no effect outside WSL.
ENV LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/usr/lib/wsl/lib

# A recent Mesa, for its d3d12 driver, through which a Windows GPU
# accelerates rendering across WSL2 (tens of times faster than software
# rendering on a large grid). Ubuntu 22.04's own Mesa (22.2) never even tries
# d3d12 and loads swrast directly; the kisak PPA's Mesa enables it.
#
# The image alone is not enough: hardware rendering needs three host
# resources, which by nature cannot be part of an image and must be passed
# to `docker run` (the repository's scripts do it, see scripts/gpu-args.ps1):
#   --device=/dev/dxg                        WSL2's GPU bridge
#   -v <DriverStore>:/usr/lib/wsl/drivers:ro the vendor driver, without which
#                                            D3D12 has nothing to drive
#   -v <wsl/lib>:/usr/lib/wsl/lib:ro         libd3d12 / libdxcore
# On NVIDIA with the Container Toolkit, `--gpus all` replaces all three: it
# injects the driver into the container, with no Mesa or driver store.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libhdf5-103 \
        git \
        software-properties-common gpg-agent && \
    add-apt-repository -y ppa:kisak/kisak-mesa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1-mesa-dri libglx-mesa0 libegl-mesa0 libgbm1 && \
    apt-get purge -y software-properties-common gpg-agent && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN install -d -o trame-user -g trame-user /deploy

# Build artefacts, as trimmed by the slim stage.
COPY --from=slim /work/pvsb-build/install /opt/paraview
COPY --from=slim /work/ttl/install-fespp /work/ttl/install-fespp

ENV TRAME_PARAVIEW=/opt/paraview

# The base image serves the static files (index.html, the widget bundles)
# with no Cache-Control, so a browser keeps serving a rebuilt bundle at the
# same URL from its cache for hours (heuristic freshness from Last-Modified;
# a plain reload revalidates only the page). no-cache makes the browser
# revalidate every time, and the ETag turns that into a 304 when nothing
# changed. Two files: the baked site config serves a container without
# TRAME_URL_PREFIX, and runtime_patch.sh renders the template over it when
# the prefix is set.
RUN for f in /etc/apache2/sites-available/001-trame.conf /opt/trame/apache.tpl; do \
      sed -i 's|^\(\s*\)FallbackResource /index.html$|&\n\1Header set Cache-Control "no-cache"|' "$f" && \
      grep -q 'Header set Cache-Control "no-cache"' "$f" || exit 1; \
    done

# The application.
COPY --chown=trame-user:trame-user ./setup /deploy/setup
COPY --chown=trame-user:trame-user ./fespp_on_trame /deploy/fespp_on_trame
COPY --chown=trame-user:trame-user ./setup.cfg /deploy/setup.cfg
COPY --chown=trame-user:trame-user ./setup.py /deploy/setup.py

# Widgets: the trame_* packages live under widgets/<name>/. apps.yml lists
# their JS bundles in www_modules and the app imports them when a session
# starts, so they must be importable from the venv, or the session dies at
# launch ("Session did not start before timeout").
COPY --chown=trame-user:trame-user ./widgets /tmp/widgets

# The session pool (deploy/pool): sessions ready before anyone asks. The
# image keeps both launchers; FESPP_POOL=1 at `docker run` picks the pool.
COPY --chown=trame-user:trame-user ./deploy/pool /deploy/pool

# Data files shipped with the image.
COPY ./data /deploy/data

# The Python dependencies and the application, installed into the trame venv.
RUN /opt/trame/entrypoint.sh build && \
    . /opt/trame/activate_venv.sh && \
    cd /deploy && \
    uv pip install -r setup/requirements.txt && \
    uv pip install . && \
    # Widget packages: a plain copy into the venv's site-packages (they are
    # pure Python plus prebuilt JS bundles, with no build step).
    SP=$(python -c "import site; print(site.getsitepackages()[0])") && \
    for d in /tmp/widgets/*/trame_*; do \
      if [ -d "$d" ]; then cp -r "$d" "$SP/"; fi; \
    done && \
    rm -rf /tmp/widgets && \
    # The pool's run.sh dispatches between the pool and wslink's launcher,
    # kept as run-wslink.sh (the scripts may come from Windows: CRLF out).
    cp -n /opt/trame/run.sh /opt/trame/run-wslink.sh && \
    for s in run.sh run-pool.sh; do tr -d '\r' < /deploy/pool/$s > /deploy/pool/$s.lf && mv /deploy/pool/$s.lf /deploy/pool/$s; done && \
    cp /deploy/pool/run.sh /opt/trame/run.sh && \
    chmod 755 /opt/trame/run.sh /opt/trame/run-wslink.sh /deploy/pool/run-pool.sh && \
    # Regenerate the www directory AFTER the requirements are installed.
    # The first `entrypoint.sh build` runs generate_www.py, which calls
    # `python -m trame.tools.www` through subprocess.run(...) WITHOUT
    # check=True: if trame is not fully resolvable from the subprocess at
    # that point, the command fails silently and /deploy/server/www stays
    # empty. An empty www directory makes Apache's
    # `FallbackResource /index.html` loop on itself (AH00125 subrequest
    # nesting), an HTTP 500 on the first browser request. Rebuilding www
    # here, once `uv pip install` has put trame in the venv, guarantees the
    # static client is in place before the build ends.
    /opt/trame/entrypoint.sh build www && \
    # Sanity check: fail the build loudly if the www directory is still
    # empty. A failed build is better than a runtime 500 with nothing in
    # the logs.
    test -s /deploy/server/www/index.html && \
    # The same for EVERY module listed in apps.yml: a widget the app enables
    # but whose bundle is missing from www makes Apache answer its .js
    # request with index.html (FallbackResource), and the client dies on
    # `Uncaught SyntaxError: Unexpected token '<'`: the browser stays on the
    # loading screen forever while the server log looks perfectly healthy.
    for m in $(sed -n 's/^[[:space:]]*-[[:space:]]*\(trame_[a-z0-9_]*\)\.module[[:space:]]*$/\1/p' /deploy/setup/apps.yml); do \
      ls -d /deploy/server/www/__${m}_* >/dev/null || exit 1; \
    done

# The BlockScope-Native engine (engine/blockscope/__init__.py) is behind a
# feature flag, which must reach the SESSION process: without it wire_view
# silently falls back to the per-representation pipeline, and the Globe view
# renders as a plain 3D view (no Earth, raw coordinates). The wslink launcher
# passes the container environment down to pvpython, so a Dockerfile ENV is
# enough (TRAME_PARAVIEW reaches the session the same way). Kept last: an
# ENV line invalidates the cache of every later layer.
ENV FESPP_BLOCKSCOPE=1
# The lazy ETP load of FESPP (opt-in in the plugin, off for a ParaView
# user): the properties, frames and skeleton of a dataspace stay on the
# store at load, placed from the discovery's edges, and the application
# reads them in the background (boot._lazy_enrich). ADME, demo/Volve: 15 s
# to 5 s, 2026-10-14. FESPP_ETP_LAZY_SKELETON=0 keeps the skeleton loaded.
ENV FESPP_ETP_LAZY_LEAVES=1
