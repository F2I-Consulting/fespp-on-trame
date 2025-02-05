FROM paraview_builder:0.0.0 AS builder

ARG GRID_EXTRACTOR_PLUGIN_PATH=gep/gridextractorplugin

# paraview build options
ENV PARALLEL_NB=6
ENV PVSB_GIT_TAG="v5.13.0"
ENV RENDERING_BACKEND="EGL"
ENV ENABLE="-DENABLE_hdf5=ON"
ENV USE_SYSTEM="-DUSE_SYSTEM_hdf5=ON -DUSE_SYSTEM_zlib=ON"

# build paraview
RUN /work/build.bash

# total stuff specific dependencies
RUN apt update && apt install -y libboost-all-dev sqlite3 libxml2-dev libfreetype-dev

ENV FESPP_BUILD_ROOT_DIR=/work/ttl

COPY ./fespp/build_scripts/build-fesapi-dependencies.sh /root/build-fesapi-dependencies.sh
COPY ./fespp/build_scripts/build-fesapi.sh /root/build-fesapi.sh
COPY ./fespp/build_scripts/build.sh /root/build.sh

# build total stuff
# RUN bash /root/build.sh
RUN bash /root/build-fesapi-dependencies.sh
RUN bash /root/build-fesapi.sh

COPY ./fespp/build_scripts/build-fespp.sh /root/build-fespp.sh
RUN bash /root/build-fespp.sh

RUN mkdir /work/ttl/gep
ENV GEP_BUILD_ROOT_DIR=/work/ttl/gep

# build grid extractor plugin
COPY $GRID_EXTRACTOR_PLUGIN_PATH /work/ttl/gep/gridextractorplugin
COPY ./gep/build_scripts/build.sh /root/build-gep.sh

RUN bash /root/build-gep.sh

FROM --platform=linux/amd64 kitware/trame:py3.10-1.2-glvnd-runtime-ubuntu22.04 AS runtime

RUN apt update && apt install -y libhdf5-103

RUN install -d -o trame-user -g trame-user /deploy

COPY --from=builder /work/pvsb-build/install /opt/paraview
COPY --from=builder /work/ttl /work/ttl

ENV TRAME_PARAVIEW=/opt/paraview

COPY --chown=trame-user:trame-user ./setup /deploy/setup
COPY --chown=trame-user:trame-user ./public /deploy/public
COPY --chown=trame-user:trame-user ./wish_wells_viewer /deploy/wish_wells_viewer
COPY --chown=trame-user:trame-user ./setup.cfg /deploy/setup.cfg
COPY --chown=trame-user:trame-user ./setup.py /deploy/setup.py

# bring some data into the image
COPY ./data /deploy/data

RUN /opt/trame/entrypoint.sh build && . /opt/trame/activate_venv.sh && cd /deploy && pip3 install .
