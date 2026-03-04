#!/bin/bash
build_root_dir=${FESPP_BUILD_ROOT_DIR:-"/work/ttl"}
deps_dir=${build_root_dir}/dependencies
echo "Building in: ${build_root_dir}"
echo "Dependencies dir: ${deps_dir}"
mkdir -p "$deps_dir" || { echo "Failed to create directory: $deps_dir"; exit 1; }
cd "$deps_dir" || { echo "Failed to cd to: $deps_dir"; exit 1; }
mkdir -p $deps_dir
cd $deps_dir

AVRO_VERSION="1.12.1"
echo "--- Downloading and Building Avro C++ (Version $AVRO_VERSION) ---"
git clone https://github.com/apache/avro.git
cd avro/
git checkout release-$AVRO_VERSION

cd ..
mkdir avro-cpp-build
mkdir install-avro
cd avro-cpp-build

cmake ../avro/lang/c++/ \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_INSTALL_PREFIX=$deps_dir/install-avro \
    -DAVRO_BUILD_TESTS=OFF || { echo "CMake configuration failed"; exit 1; }
cmake --build . -j$(nproc) || { echo "Build failed"; exit 1; }
cmake --install . || { echo "Install failed"; exit 1; }

rm -Rf $deps_dir/avro
rm -Rf $deps_dir/avro-cpp-build

ls -R $deps_dir/install-avro

echo "--- Avro ${AVRO_VERSION} build completed successfully ---"
