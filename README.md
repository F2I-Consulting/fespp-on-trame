# fespp-on-trame

## create Paraview builder base image
cd pv_docker
docker build -t paraview_builder:0.0.0 .

## create Trame Application image
cd ..
docker build -t trame_app:0.0.0 .

if error:
--------------------
  39 |     RUN bash /root/build-gep.sh
  40 |
  41 | >>> FROM --platform=linux/amd64 kitware/trame:py3.10-1.2-glvnd-runtime-ubuntu22.04 AS runtime
  42 |
  43 |     RUN apt update && apt install -y libhdf5-103
--------------------
ERROR: failed to solve: kitware/trame:py3.10-1.2-glvnd-runtime-ubuntu22.04: failed to resolve source metadata for docker.io/kitware/trame:py3.10-1.2-glvnd-runtime-ubuntu22.04: failed to do request: Head "https://registry-1.docker.io/v2/kitware/trame/manifests/py3.10-1.2-glvnd-runtime-ubuntu22.04": EOF

=> docker pull manually
docker pull kitware/trame:py3.10-1.2-glvnd-runtime-ubuntu22.04

## run image
docker run -it --rm -p 8080:80 trame_app:0.0.0