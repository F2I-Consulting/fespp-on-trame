#!/bin/bash
# Build the whole chain by hand, in the same order as the Dockerfile's RUN
# steps. fetpapi must build after fesapi (it is built WITH_FESAPI) and before
# fespp, which links against it for the ETP/OSDU source (ETP12Store).
script_dir=$(dirname $0)
${script_dir}/build-fesapi-dependencies.sh
${script_dir}/build-fesapi.sh
${script_dir}/build-fetpapi-dependencies.sh
${script_dir}/build-fetpapi.sh
${script_dir}/build-fespp.sh
