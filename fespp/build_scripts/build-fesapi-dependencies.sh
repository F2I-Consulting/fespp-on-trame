#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
deps_dir=${build_root_dir}/dependencies
mkdir -p $deps_dir
cd $deps_dir
git clone https://github.com/F2I-Consulting/Minizip.git
mkdir -p $deps_dir/build-minizip
mkdir -p $deps_dir/install-minizip
cd $deps_dir/build-minizip
cmake -DCMAKE_INSTALL_PREFIX=$deps_dir/install-minizip $deps_dir/Minizip
cmake --build . --parallel
cmake --install .
