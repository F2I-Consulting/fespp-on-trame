# ============================================================================
# Builder stage - Compile ParaView et FESPP
# ============================================================================
FROM paraview:6.0.x AS builder

ENV PARALLEL_NB=12
ENV PVSB_GIT_TAG="v6.0.1"
ENV ENABLE="-DENABLE_hdf5=ON"
ENV USE_SYSTEM="-DUSE_SYSTEM_hdf5=ON -DUSE_SYSTEM_zlib=ON"

RUN sh /work/build.bash

# Build FESPP
ENV FESPP_BUILD_ROOT_DIR=/work/ttl

# total stuff specific dependencies
RUN apt update && apt install -y libboost-all-dev sqlite3 libxml2-dev libfreetype-dev

COPY ./fespp/build_scripts/build-fesapi-dependencies.sh /root/build-fesapi-dependencies.sh
COPY ./fespp/build_scripts/build-fesapi.sh /root/build-fesapi.sh
COPY ./fespp/build_scripts/build-fetpapi-dependencies.sh /root/build-fetpapi-dependencies.sh
COPY ./fespp/build_scripts/build-fetpapi.sh /root/build-fetpapi.sh
COPY ./fespp/build_scripts/build-fespp.sh /root/build-fespp.sh

RUN bash /root/build-fesapi-dependencies.sh
RUN bash /root/build-fesapi.sh
RUN bash /root/build-fetpapi-dependencies.sh
RUN bash /root/build-fetpapi.sh

# Build mode: local (copy from host) or github (git clone)
COPY fespp-src-local* ${FESPP_BUILD_ROOT_DIR}/fespp/

RUN bash /root/build-fespp.sh

# ============================================================================
# Runtime stage
# ============================================================================
FROM kitware/trame:uv-1.2-glvnd-runtime-ubuntu22.04 AS runtime

# Variables d'environnement pour GPU
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libhdf5-103 \
        git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN install -d -o trame-user -g trame-user /deploy

# Copie des artefacts de build
COPY --from=builder /work/pvsb-build/install /opt/paraview
COPY --from=builder /work/ttl /work/ttl

ENV TRAME_PARAVIEW=/opt/paraview

# Copie de l'application
COPY --chown=trame-user:trame-user ./setup /deploy/setup
COPY --chown=trame-user:trame-user ./public /deploy/public
COPY --chown=trame-user:trame-user ./fespp_on_trame /deploy/fespp_on_trame
COPY --chown=trame-user:trame-user ./setup.cfg /deploy/setup.cfg
COPY --chown=trame-user:trame-user ./setup.py /deploy/setup.py

# Données
COPY ./data /deploy/data

# Installation des dépendances Python et de l'application
RUN /opt/trame/entrypoint.sh build && \
    . /opt/trame/activate_venv.sh && \
    cd /deploy && \
    uv pip install -r setup/requirements.txt && \
    uv pip install .