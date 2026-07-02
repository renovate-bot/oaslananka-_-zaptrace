FROM python:3.14-slim AS builder
WORKDIR /build
RUN pip install maturin uv
RUN apt-get update && apt-get install -y curl build-essential && \
    curl https://sh.rustup.rs -sSf | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"
COPY . .
RUN maturin build --release --out dist --manifest-path zaptrace_core/Cargo.toml

FROM python:3.14-slim
WORKDIR /app
# Bundle ngspice so the DC operating-point simulation gate is real in the
# container/CI: a skipped gate then means an environment fault, not an accepted gap.
RUN apt-get update && apt-get install -y --no-install-recommends ngspice && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/dist/*.whl /app/dist/
RUN mkdir -p /workspace && \
    WHEEL="$(find /app/dist -name '*.whl' -print -quit)" && \
    pip install --no-cache-dir "${WHEEL}[mcp,server]" && rm -rf /app/dist && \
    addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 appuser --ingroup appgroup && \
    chown -R appuser:appgroup /workspace
VOLUME ["/workspace"]
WORKDIR /workspace
USER appuser:appgroup
ENTRYPOINT ["zaptrace"]
CMD ["--help"]
