#!/bin/bash
script_dir=$(dirname $0)
${script_dir}/build-fesapi-dependencies.sh
${script_dir}/build-fesapi.sh
${script_dir}/build-fespp.sh
