# fespp_ia: the local AI service of fespp_on_trame: a gateway (fespp_ia.server)
# in front of llama-server, plus the RAG over the indexed documentation.
#
#   docker build -t fespp_ia:cpu  ia                                   (ia\build.ps1)
#   docker build -t fespp_ia:cuda ia --build-arg LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda --build-arg GPU_LAYERS=99
#
# The base is llama.cpp's own server image: llama-server already built for
# the target (every CPU flavour, or CUDA). We add the gateway, the only door
# of the service. NO model in the image: they come from the /models volume.
ARG LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server@sha256:6257697a7f5d034b8fb499ddb07af3e250506352f94102054252a23f3b85e0af
FROM ${LLAMA_IMAGE}

ARG GPU_LAYERS=0
ENV FESPP_IA_GPU_LAYERS=${GPU_LAYERS} \
    FESPP_IA_MODELS=/models \
    FESPP_IA_INDEX=/models/index \
    FESPP_IA_EMBED=/models/embed/bilingual-embedding-small \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv curl \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv

COPY requirements.txt /opt/fespp_ia/requirements.txt
# torch from the CPU index first: sentence-transformers (the RAG's
# embeddings) needs it, and the default wheel pulls in about 2 GB of CUDA
# libraries the embeddings never use
RUN pip install --no-cache-dir torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /opt/fespp_ia/requirements.txt

COPY fespp_ia /opt/fespp_ia/fespp_ia
COPY tests /opt/fespp_ia/tests
WORKDIR /opt/fespp_ia
ENV PYTHONPATH=/opt/fespp_ia

VOLUME /models
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD curl -fs http://127.0.0.1:8000/v1/health | grep -q '"status":"ok"' || exit 1
ENTRYPOINT ["python3", "-m", "fespp_ia.server"]
