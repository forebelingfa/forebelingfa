# ---------- Builder ----------
FROM debian:12-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (minimal profile)
ENV RUSTUP_HOME=/rustup \
    CARGO_HOME=/cargo \
    PATH=/cargo/bin:$PATH

RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal

# ---------- Runtime ----------
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Runtime-only deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    git \
    screen \
    && rm -rf /var/lib/apt/lists/*

# Copy Rust toolchain only
COPY --from=builder /cargo /cargo
COPY --from=builder /rustup /rustup

ENV CARGO_HOME=/cargo \
    RUSTUP_HOME=/rustup \
    PATH=/cargo/bin:$PATH

# Non-root user
RUN useradd -m -s /bin/bash rust
USER rust
WORKDIR /home/rust

RUN echo "startup_message off" > ~/.screenrc

CMD ["/bin/bash"]
