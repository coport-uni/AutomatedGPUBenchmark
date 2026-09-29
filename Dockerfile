# syntax=docker/dockerfile:1
# Runtime image for AutomatedGPUBenchmark (DevSpec sections 1.4, 4.8).
#
# Stage 1 compiles gpu_burn and cuda_memtest from pinned sources with the
# CUDA toolkit. Stage 2 keeps the binaries, the CUDA runtime libraries,
# and the gpubench package. The container runs without --privileged:
#   docker run -d --init --gpus all -v ./results:/results gpubench

ARG CUDA_VERSION=12.8.1
ARG UBUNTU_VERSION=24.04

# --------------------------------------------------------------------
FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS builder

# Fat binary targets, Pascal through Blackwell. CUDA 12.8 is the last
# major line that still compiles for sm_6x while knowing sm_100/120.
ARG CUDA_ARCHS="61;70;75;80;86;89;90;100;120"
ARG GPU_BURN_REF=3ead140434da9473582b68452f7115967a7a0581
ARG CUDA_MEMTEST_REF=e94e1ee54e0689c9f154a8a08202554452552ec6

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates cmake g++ git make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# gpu-burn's Makefile accepts one COMPUTE value; an empty COMPUTE plus
# explicit -gencode flags yields a fat binary (README, "make COMPUTE=").
# The last architecture also embeds PTX so newer GPUs can JIT.
RUN git clone https://github.com/wilicc/gpu-burn.git \
    && git -C gpu-burn checkout --quiet "${GPU_BURN_REF}" \
    && gencode="" \
    && for arch in $(echo "${CUDA_ARCHS}" | tr ';' ' '); do \
        gencode="${gencode} -gencode arch=compute_${arch},code=sm_${arch}"; \
        last="${arch}"; \
    done \
    && gencode="${gencode} -gencode arch=compute_${last},code=compute_${last}" \
    && make -C gpu-burn COMPUTE= NVCCFLAGS="${gencode}" \
    && install -D -m 0755 gpu-burn/gpu_burn /opt/gpu-burn/gpu_burn \
    && install -D -m 0644 gpu-burn/compare.fatbin /opt/gpu-burn/compare.fatbin

RUN git clone https://github.com/ComputationalRadiationPhysics/cuda_memtest.git \
    && git -C cuda_memtest checkout --quiet "${CUDA_MEMTEST_REF}" \
    && cmake -S cuda_memtest -B cuda_memtest/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHS}" \
    && cmake --build cuda_memtest/build -j"$(nproc)" \
    && install -D -m 0755 cuda_memtest/build/cuda_memtest \
        /usr/local/bin/cuda_memtest

# --------------------------------------------------------------------
# OOXML schemas for the report.docx check (DevSpec 4.6.1, step 3):
# ECMA-376 5th edition Part 4 Transitional XSDs plus the W3C xml.xsd,
# pinned by SHA-256.
FROM ubuntu:${UBUNTU_VERSION} AS schemas

ARG ECMA_URL=https://ecma-international.org/wp-content/uploads/ECMA-376-4_5th_edition_december_2016.zip
ARG ECMA_SHA256=bd25da1109f73762356596918bf5ff8b74a1331642dba5f1c1d1dfc6bed34ecd
ARG ECMA_XSD_ZIP=OfficeOpenXML-XMLSchema-Transitional.zip
ARG ECMA_XSD_SHA256=d34187520749998af306faf1b730e568b0ca6d88ad24638a407c0a9bb4ca04fc
ARG XML_XSD_URL=https://www.w3.org/2001/xml.xsd
ARG XML_XSD_SHA256=61960fb3131e38022caad5360e2f33a3382578ab3c80cd58bd74320ede61b20c

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/ecma
RUN curl -fsSL -o ecma.zip "${ECMA_URL}" \
    && echo "${ECMA_SHA256}  ecma.zip" | sha256sum -c - \
    && unzip -q ecma.zip "${ECMA_XSD_ZIP}" \
    && echo "${ECMA_XSD_SHA256}  ${ECMA_XSD_ZIP}" | sha256sum -c - \
    && mkdir -p /opt/ooxml-schemas \
    && unzip -q "${ECMA_XSD_ZIP}" -d /opt/ooxml-schemas \
    && curl -fsSL -o /opt/ooxml-schemas/xml.xsd "${XML_XSD_URL}" \
    && echo "${XML_XSD_SHA256}  /opt/ooxml-schemas/xml.xsd" \
        | sha256sum -c -

# --------------------------------------------------------------------
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

# compute: CUDA for the test tools; utility: nvidia-smi and NVML.
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    GPUBENCH_CONFIG_DIR=/app/config \
    GPUBENCH_OOXML_SCHEMAS=/opt/ooxml-schemas \
    PATH=/opt/venv/bin:/opt/gpu-burn:${PATH}

# LibreOffice Writer and python3-uno convert report.docx to PDF; Noto
# CJK renders Korean in the charts and the PDF (DevSpec 4.6.1). The venv
# sees the system site-packages because uno only ships as a
# distribution package.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
        --no-install-recommends \
        python3 python3-venv python3-uno libreoffice-writer-nogui \
        fonts-noto-cjk tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip

COPY --from=builder /opt/gpu-burn /opt/gpu-burn
COPY --from=builder /usr/local/bin/cuda_memtest /usr/local/bin/cuda_memtest
COPY --from=schemas /opt/ooxml-schemas /opt/ooxml-schemas

# Driver library stubs, outside the default search path. They let the
# tool binaries load on a machine without a GPU for --help smoke tests:
#   docker run --rm -e LD_LIBRARY_PATH=/opt/cuda-stubs gpubench gpu_burn -h
COPY --from=builder /usr/local/cuda/lib64/stubs/libcuda.so \
    /opt/cuda-stubs/libcuda.so.1
COPY --from=builder /usr/local/cuda/lib64/stubs/libnvidia-ml.so \
    /opt/cuda-stubs/libnvidia-ml.so.1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN /opt/venv/bin/pip install --no-cache-dir .

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

VOLUME ["/results"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# The container stays resident; tests run through docker exec.
CMD ["sleep", "infinity"]
