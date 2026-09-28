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
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

# compute: CUDA for the test tools; utility: nvidia-smi and NVML.
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    GPUBENCH_CONFIG_DIR=/app/config \
    PATH=/opt/venv/bin:/opt/gpu-burn:${PATH}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip

COPY --from=builder /opt/gpu-burn /opt/gpu-burn
COPY --from=builder /usr/local/bin/cuda_memtest /usr/local/bin/cuda_memtest

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
