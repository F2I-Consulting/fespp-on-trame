#!/bin/bash

build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
deps_dir=${build_root_dir}/dependencies
mkdir -p $deps_dir
cd $deps_dir

git clone https://github.com/F2I-Consulting/Minizip.git
mkdir build-minizip
mkdir install-minizip
cd build-minizip/
cmake -DCMAKE_INSTALL_PREFIX=/work/ttl/dependencies/install-minizip /work/ttl/dependencies/Minizip
cmake --build . --parallel
cmake --install .
