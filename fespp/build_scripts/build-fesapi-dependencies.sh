#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
deps_dir=${build_root_dir}/dependencies
echo "Building in: ${build_root_dir}"
echo "Dependencies dir: ${deps_dir}"
mkdir -p "$deps_dir" || { echo "Failed to create directory: $deps_dir"; exit 1; }
cd "$deps_dir" || { echo "Failed to cd to: $deps_dir"; exit 1; }
mkdir -p $deps_dir
cd $deps_dir
git clone https://github.com/F2I-Consulting/Minizip.git
mkdir -p $deps_dir/build-minizip
mkdir -p $deps_dir/install-minizip
cd $deps_dir/build-minizip
cmake -DCMAKE_INSTALL_PREFIX=$deps_dir/install-minizip $deps_dir/Minizip
cmake --build . || { echo "Build failed"; exit 1; }
cmake --install . || { echo "Install failed"; exit 1; }
echo "Minizip build completed successfully"
