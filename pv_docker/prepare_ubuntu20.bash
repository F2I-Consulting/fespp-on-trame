#!/bin/bash
apt-get -y update && apt-get upgrade -y && \
apt-get remove --purge --auto-remove cmake && \
apt-get install -y \
    software-properties-common lsb-release patchelf ninja-build bison flex libx11-dev libpng-dev curl \
    git pkg-config build-essential file libgl1-mesa-dev libhdf5-dev ca-certificates gpg wget zlib1g-dev libpthread-stubs0-dev && \
apt-get clean all &&
mkdir -p /opt/cmake/3.28.0 && cd /opt/cmake/3.28.0 && \
curl -L https://cmake.org/files/v3.28/cmake-3.28.0-linux-x86_64.tar.gz | tar --strip-components=1 -xzv && \
ln -s /opt/cmake/3.28.0/bin/cmake /usr/bin/cmake && \
ln -s /opt/cmake/3.28.0/bin/cpack /usr/bin/cpack && \
ln -s /opt/cmake/3.28.0/bin/ctest /usr/bin/ctest && \

mkdir /work
cd /work && git clone --recursive https://gitlab.kitware.com/paraview/paraview-superbuild.git pvsb-sources
